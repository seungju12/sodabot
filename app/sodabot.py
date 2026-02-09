import os
import asyncio
import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") # 토큰을 가져오기 위해 .env 로드

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

lobbies: dict[int, dict] = {}

# 포지션과 티어 정의
POSITIONS = ["탑", "정글", "미드", "원딜", "서포터"]
TIERS = ["아이언", "브론즈", "실버", "골드", "플래티넘", "에메랄드", "다이아", "마스터", "마스터+300", "그랜드마스터", "챌린저"]
MAPS = ["소환사의 협곡", "무작위 총력전", "무작위 총력전: 아수라장"]
HOURS = [f"{h:02d}" for h in range(24)]  # 0~23시
MINUTES = ["00", "30"]  # 00분, 30분


def lobby_embed(lobby: dict) -> discord.Embed:
    members = lobby["members"]
    cap = lobby["capacity"]
    status = lobby["status"]
    start_time = lobby.get("start_time", "미설정")
    map_name = lobby.get("map", "미설정")

    status_kr = {
        "open": "모집 중",
        "closed": "마감",
        "cancelled": "취소됨",
        "started": "시작됨"
    }.get(status, status)

    # 참가자 정보를 포지션, 티어와 함께 표시
    member_lines = []
    for uid, info in members.items():
        if isinstance(info, dict):
            position = info.get("position")
            tier = info.get("tier")
        else:
            position = None
            tier = None
        
        invalid_vals = {None, "무관", "?", "미설정", ""}
        # position may be a list (주/부) or a string
        if isinstance(position, list):
            # filter invalid entries
            filtered = [p for p in position if p not in invalid_vals]
            position_display = " / ".join(filtered) if filtered else None
        else:
            position_display = position

        show_extra = (position_display not in invalid_vals) and (tier not in invalid_vals)
        if show_extra:
            member_lines.append(f"<@{uid}> [{position_display} | {tier}]")
        else:
            member_lines.append(f"<@{uid}>")
    member_text = "\n".join(member_lines) if member_lines else "(아직 없음)"

    e = discord.Embed(
        title=f"🎮 {lobby['title']}",
        description=f"상태: **{status_kr}**\n맵: **{map_name}**\n정원: **{len(members)}/{cap}**\n시작시간: **{start_time}**",
        color=discord.Color.blurple(),
    )
    e.add_field(name="참가자", value=member_text, inline=False)
    e.set_footer(text=f"호스트: {lobby.get('host_name', '알 수 없음')}")
    return e


class SelectModal(discord.ui.Modal, title="포지션과 티어 선택"):
    def __init__(self, lobby_message_id: int):
        super().__init__()
        self.lobby_message_id = lobby_message_id

    async def on_submit(self, interaction: discord.Interaction):
        pass


 


class CreateLobbyModal(discord.ui.Modal, title="내전 로비 생성"):
    제목 = discord.ui.TextInput(label="내전 제목", placeholder="예: 협곡 내전", default="협곡 내전")
    정원 = discord.ui.TextInput(label="모집 인원", placeholder="예: 10", default="10")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            capacity = int(self.정원.value)
        except ValueError:
            await interaction.response.send_message("정원은 숫자여야 합니다.", ephemeral=True)
            return

        if capacity < 2 or capacity > 20:
            await interaction.response.send_message("정원은 2~20 사이로 설정해 주세요.", ephemeral=True)
            return

        # 임시 로비 데이터 (맵/시간은 팝업에서 선택)
        lobby = {
            "host_id": interaction.user.id,
            "host_name": interaction.user.display_name,
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "title": self.제목.value,
            "capacity": capacity,
            "members": {},
            "status": "open",
            "start_time": "미설정",
            "map": "미설정",
        }

        # 단일 에페메럴 팝업에서 맵/시간 선택 후 생성하도록 하는 뷰 표시
        view = FinalizeLobbyView(lobby)
        content = "📍 맵과 시간을 선택한 뒤 '생성' 버튼을 눌러주세요."
        await interaction.response.send_message(content, view=view, ephemeral=True)


class FinalizeLobbyView(discord.ui.View):
    def __init__(self, lobby: dict):
        super().__init__(timeout=180)
        self.lobby = lobby
        self.add_item(MapSelectSimple(self.lobby))
        self.add_item(HourSelectSimple(self.lobby))

    async def update_interaction_message(self, interaction: discord.Interaction):
        # 현재 선택 상태를 임베드로 보여줘 눈에 띄게 함
        map_name = self.lobby.get("map", "미설정")
        start_time = self.lobby.get("start_time", "미설정")
        # 강조 색상: 선택 완료 시 초록, 아니면 노란
        color = discord.Color.green() if map_name != "미설정" and start_time != "미설정" else discord.Color.gold()
        embed = discord.Embed(title="로비 생성 설정", color=color)
        embed.add_field(name="맵", value=f"🔹 {map_name}", inline=True)
        embed.add_field(name="시작시간", value=f"🕒 {start_time}", inline=True)
        embed.set_footer(text="모두 선택한 뒤 '생성'을 누르세요.")
        try:
            await interaction.response.edit_message(content=None, embed=embed, view=self)
        except Exception:
            # 이미 응답이 된 경우에는 followup
            try:
                await interaction.followup.edit_message(message_id=interaction.message.id, content=None, embed=embed, view=self)
            except Exception:
                pass

    @discord.ui.button(label="생성", style=discord.ButtonStyle.success, custom_id="finalize:create")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 필수 선택 확인
        if self.lobby.get("map") == "미설정" or self.lobby.get("start_time") == "미설정":
            await interaction.response.send_message("맵과 시작 시간을 모두 선택해야 합니다.", ephemeral=True)
            return

        # 공개 채널에 로비 생성
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        # 멘션을 본문에 포함하지 않음 — 임베드와 뷰만 전송
        msg = await channel.send(embed=lobby_embed(self.lobby), view=LobbyViewPlaceholder(self.lobby))

        lobby_message_id = msg.id
        lobbies[lobby_message_id] = self.lobby

        # 실제 LobbyView를 붙여 메시지 갱신
        view = LobbyView(lobby_message_id)
        view.join_button.disabled = False
        view.leave_button.disabled = False
        view.close_button.disabled = False
        view.start_button.disabled = False
        await msg.edit(embed=lobby_embed(self.lobby), view=view)


class MapSelectSimple(discord.ui.Select):
    def __init__(self, lobby: dict):
        self.lobby = lobby
        super().__init__(
            placeholder="맵 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=map_name) for map_name in MAPS]
        )

    async def callback(self, interaction: discord.Interaction):
        self.lobby["map"] = self.values[0]
        # 에페메럴 메시지 업데이트
        view = self.view
        if isinstance(view, FinalizeLobbyView):
            await view.update_interaction_message(interaction)


class HourSelectSimple(discord.ui.Select):
    def __init__(self, lobby: dict):
        self.lobby = lobby
        super().__init__(
            placeholder="시간 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=f"{h}시", value=f"{h:02d}:00") for h in range(24)]
        )

    async def callback(self, interaction: discord.Interaction):
        # 시작 시간을 바로 설정 (분 선택 없음)
        self.lobby["start_time"] = self.values[0]
        # 에페메럴 메시지 업데이트
        view = self.view
        if isinstance(view, FinalizeLobbyView):
            await view.update_interaction_message(interaction)


# Minute selection removed — time granularity is hourly (HH:00)


class LobbyViewPlaceholder(discord.ui.View):
    # 임시 자리표시용 뷰 (버튼 객체는 LobbyView에서 재생성)
    def __init__(self, lobby: dict):
        super().__init__()


class JoinSelectionView(discord.ui.View):
    def __init__(self, lobby_message_id: int):
        super().__init__(timeout=180)
        self.lobby_message_id = lobby_message_id
        self.lobby = lobbies.get(lobby_message_id, {})
        self.selected_tier: str | None = None
        self.selected_position: str | None = None
        self.add_item(TierJoinSelect())
        self.add_item(PositionJoinSelect())

    async def update_interaction_message(self, interaction: discord.Interaction):
        tier = self.selected_tier or "미설정"
        pos = self.selected_position or "미설정"
        # format pos if list
        if isinstance(pos, list):
            pos_display = " / ".join(pos) if pos else "미설정"
        else:
            pos_display = pos
        embed = discord.Embed(title="참가 정보 선택", color=discord.Color.gold())
        embed.add_field(name="티어", value=f"🔹 {tier}", inline=True)
        embed.add_field(name="포지션", value=f"🛡️ {pos_display}", inline=True)
        embed.set_footer(text="선택 후 '참가' 버튼을 눌러 참가하세요.")
        try:
            await interaction.response.edit_message(content=None, embed=embed, view=self)
        except Exception:
            try:
                await interaction.followup.edit_message(message_id=interaction.message.id, content=None, embed=embed, view=self)
            except Exception:
                pass

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="join:confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = lobbies.get(self.lobby_message_id)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        if lobby["status"] != "open":
            await interaction.response.send_message("이미 마감/시작된 로비입니다.", ephemeral=True)
            return

        uid = interaction.user.id
        if uid in lobby["members"]:
            await interaction.response.send_message("이미 참가하셨습니다.", ephemeral=True)
            return

        if len(lobby["members"]) >= lobby["capacity"]:
            await interaction.response.send_message("정원이 가득 찼습니다.", ephemeral=True)
            return

        # 기본값 처리
        tier = self.selected_tier or ""
        # normalize position to display string (support list)
        if isinstance(self.selected_position, list):
            pos_val = " / ".join(self.selected_position) if self.selected_position else ""
        else:
            pos_val = self.selected_position or ""

        lobby["members"][uid] = {"position": pos_val, "tier": tier}

        # 로비 메시지 갱신 및 마감 체크
        try:
            channel = interaction.channel
            lobby_msg = await channel.fetch_message(self.lobby_message_id)
            # 마감 시 상태 변경
            if len(lobby["members"]) >= lobby["capacity"]:
                lobby["status"] = "closed"
            view = LobbyView(self.lobby_message_id)
            await lobby_msg.edit(embed=lobby_embed(lobby), view=view)

            # 마감 시 참여자 멘션으로 알림
            if lobby["status"] == "closed":
                participants = " ".join(f"<@{mid}>" for mid in lobby["members"].keys())
                await channel.send(f"✅ 모집이 완료되었습니다! 참여자: {participants}")
        except Exception as e:
            print(f"Error updating lobby message on join: {e}")

        await interaction.response.send_message("✅ 참가가 완료되었습니다!", ephemeral=True)


class TierJoinSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="티어 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=t) for t in TIERS]
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, JoinSelectionView):
            view.selected_tier = self.values[0]
            await view.update_interaction_message(interaction)


class PositionJoinSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="포지션 선택 (1,2순위)",
            min_values=2,
            max_values=2,
            options=[discord.SelectOption(label=p) for p in POSITIONS]
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, JoinSelectionView):
            # self.values may contain 1 or 2 positions
            view.selected_position = list(self.values)
            await view.update_interaction_message(interaction)


class PositionSelect(discord.ui.Select):
    def __init__(self, lobby_message_id: int, tier_value: str):
        self.lobby_message_id = lobby_message_id
        self.tier_value = tier_value
        super().__init__(
            placeholder="포지션을 선택하세요",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=pos) for pos in POSITIONS]
        )

    async def callback(self, interaction: discord.Interaction):
        lobby = lobbies.get(self.lobby_message_id)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        uid = interaction.user.id
        position = self.values[0]
        
        lobby["members"][uid] = {
            "position": position,
            "tier": self.tier_value
        }
        
        await interaction.response.send_message("✅ 참가가 완료되었습니다!", ephemeral=True)
        
        # 로비 메시지 갱신
        try:
            lobby_msg = await interaction.channel.fetch_message(self.lobby_message_id)
            # 마감 체크
            if len(lobby["members"]) >= lobby["capacity"]:
                lobby["status"] = "closed"
            view = LobbyView(self.lobby_message_id)
            await lobby_msg.edit(embed=lobby_embed(lobby), view=view)

            if lobby["status"] == "closed":
                participants = " ".join(f"<@{mid}>" for mid in lobby["members"].keys())
                await interaction.channel.send(f"✅ 모집이 완료되었습니다! 참여자: {participants}")
        except Exception as e:
            print(f"Error updating lobby message: {e}")


class TierSelect(discord.ui.Select):
    def __init__(self, lobby_message_id: int):
        self.lobby_message_id = lobby_message_id
        super().__init__(
            placeholder="티어를 선택하세요",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=tier) for tier in TIERS]
        )

    async def callback(self, interaction: discord.Interaction):
        tier = self.values[0]
        
        # 다음 단계: 포지션 선택
        view = discord.ui.View()
        view.add_item(PositionSelect(self.lobby_message_id, tier))
        await interaction.response.send_message("포지션을 선택하세요:", view=view, ephemeral=True)


class SelectionView(discord.ui.View):
    def __init__(self, lobby_message_id: int):
        super().__init__()
        self.lobby_message_id = lobby_message_id
        self.add_item(TierSelect(lobby_message_id))


class LobbyView(discord.ui.View):
    def __init__(self, lobby_message_id: int):
        super().__init__(timeout=None)
        self.lobby_message_id = lobby_message_id

    def get_lobby(self) -> dict | None:
        return lobbies.get(self.lobby_message_id)

    async def refresh_message(self, interaction: discord.Interaction):
        lobby = self.get_lobby()
        if not lobby:
            return
        # 버튼 활성/비활성 상태 갱신
        is_open = lobby["status"] == "open"
        is_started = lobby["status"] == "started"
        is_closed = lobby["status"] == "closed"

        # 참가/취소: open 일 때만 가능
        self.join_button.disabled = not is_open
        self.leave_button.disabled = not is_open

        # 호스트 버튼: closed/started 상태에 따라 비활성화
        self.close_button.disabled = (is_closed or is_started)
        self.start_button.disabled = is_started

        await interaction.message.edit(embed=lobby_embed(lobby), view=self)

    def is_host(self, interaction: discord.Interaction, lobby: dict) -> bool:
        return interaction.user.id == lobby["host_id"]

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="lobby:join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby()
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        if lobby["status"] != "open":
            await interaction.response.send_message("이미 마감/시작된 로비입니다.", ephemeral=True)
            return

        uid = interaction.user.id
        if uid in lobby["members"]:
            await interaction.response.send_message("이미 참가하셨습니다.", ephemeral=True)
            return

        if len(lobby["members"]) >= lobby["capacity"]:
            await interaction.response.send_message("정원이 가득 찼습니다.", ephemeral=True)
            return

        # 맵이 소환사의 협곡이 아닌 경우 포지션/티어 없이 자동 참가 허용
        map_name = lobby.get("map", "미설정")
        if map_name != "소환사의 협곡":
            uid = interaction.user.id
            lobby["members"][uid] = {
                "position": "무관",
                "tier": "무관"
            }
            # 공개 로비 메시지 갱신
            try:
                lobby_msg = await interaction.channel.fetch_message(self.lobby_message_id)
                # 마감 체크
                if len(lobby["members"]) >= lobby["capacity"]:
                    lobby["status"] = "closed"
                view = LobbyView(self.lobby_message_id)
                await lobby_msg.edit(embed=lobby_embed(lobby), view=view)

                if lobby["status"] == "closed":
                    participants = " ".join(f"<@{mid}>" for mid in lobby["members"].keys())
                    await interaction.channel.send(f"✅ 모집이 완료되었습니다! 참여자: {participants}")
            except Exception:
                pass
            await interaction.response.send_message("✅ 참가가 완료되었습니다!", ephemeral=True)
            return

        # 소환사의 협곡인 경우 단일 팝업에서 티어/포지션 선택
        view = JoinSelectionView(self.lobby_message_id)
        await interaction.response.send_message("티어와 포지션을 선택한 뒤 '참가' 버튼을 누르세요.", view=view, ephemeral=True)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, custom_id="lobby:leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby()
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        if lobby["status"] != "open":
            await interaction.response.send_message("마감/시작된 로비는 취소할 수 없습니다.", ephemeral=True)
            return

        uid = interaction.user.id
        if uid not in lobby["members"]:
            await interaction.response.send_message("참가 상태가 아닙니다.", ephemeral=True)
            return

        del lobby["members"][uid]
        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="마감", style=discord.ButtonStyle.danger, custom_id="lobby:close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby()
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 마감할 수 있습니다.", ephemeral=True)
            return

        if lobby["status"] != "open":
            await interaction.response.send_message("이미 마감/시작된 로비입니다.", ephemeral=True)
            return

        lobby["status"] = "closed"
        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="시작", style=discord.ButtonStyle.primary, custom_id="lobby:start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby()
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 시작할 수 있습니다.", ephemeral=True)
            return

        if lobby["status"] == "started":
            await interaction.response.send_message("이미 시작된 로비입니다.", ephemeral=True)
            return

        lobby["status"] = "started"
        await interaction.response.defer()
        await self.refresh_message(interaction)

    @discord.ui.button(label="내전 취소", style=discord.ButtonStyle.danger, custom_id="lobby:cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby()
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 취소할 수 있습니다.", ephemeral=True)
            return

        # 참가자들에게 취소 알림(멘션)
        participants = " ".join(f"<@{mid}>" for mid in lobby.get("members", {}).keys())
        channel = interaction.channel
        try:
            if participants:
                await channel.send(f"❌ 호스트가 내전을 취소했습니다. 참여자: {participants}")
            else:
                await channel.send("❌ 호스트가 내전을 취소했습니다.")
        except Exception:
            pass

        # 로비 삭제 혹은 상태 변경
        lobby["status"] = "cancelled"
        lobbies.pop(self.lobby_message_id, None)

        # 메시지 갱신: 상태를 반영한 임베드로 바꿈
        try:
            lobby_msg = await channel.fetch_message(self.lobby_message_id)
            await lobby_msg.edit(embed=lobby_embed(lobby), view=None)
        except Exception:
            pass

        await interaction.response.send_message("로비를 취소했습니다.", ephemeral=True)


class CreateLobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎮 내전 로비 생성", style=discord.ButtonStyle.blurple, custom_id="create_lobby_btn")
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateLobbyModal())


@client.event
async def on_ready():
    try:
        await tree.sync()
    except Exception as e:
        print(f"Error syncing commands: {e}")
    
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    
    # CreateLobbyView를 persistent view로 등록 (기존 메시지 버튼도 작동하도록)
    client.add_view(CreateLobbyView())
    print("CreateLobbyView registered")
    
    # 로비 생성 버튼이 있는 메시지를 각 채널에 보냄
    for guild in client.guilds:
        # 첫 번째 텍스트 채널에 버튼 보내기
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                # 이미 있는 메시지가 있는지 확인 (있으면 건너뜀)
                async for msg in channel.history(limit=10):
                    if msg.author == client.user and len(msg.components) > 0:
                        print("Existing lobby button message found")
                        return
                
                # 없으면 새로 생성
                embed = discord.Embed(
                    title="🎮 롤 내전 로비",
                    description="아래 버튼을 클릭하여 로비를 생성하세요!",
                    color=discord.Color.blurple()
                )
                await channel.send(embed=embed, view=CreateLobbyView())
                print("New lobby button message created")
                return


client.run(TOKEN)