import os
import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)

lobbies: dict[int, dict] = {}

# 포지션/티어/맵
POSITIONS = ["탑", "정글", "미드", "원딜", "서포터"]
TIERS = ["아이언", "브론즈", "실버", "골드", "플래티넘", "에메랄드", "다이아", "마스터", "마스터+300", "그랜드마스터", "챌린저"]
MAPS = ["소환사의 협곡", "무작위 총력전", "무작위 총력전: 아수라장"]


def lobby_embed(lobby: dict) -> discord.Embed:
    members = lobby["members"]
    cap = lobby["capacity"]
    status = lobby["status"]
    start_time = lobby.get("start_time", "미설정")
    map_name = lobby.get("map", "미설정")

    status_kr = {"open": "모집 중", "closed": "마감", "cancelled": "취소됨", "started": "시작됨"}.get(status, status)

    # 참가자 표기: 협곡만 포지션/티어 표시, 그 외는 멘션만
    if map_name == "소환사의 협곡":
        member_lines = []
        for uid, info in members.items():
            position = info.get("position")
            tier = info.get("tier")

            if isinstance(position, list):
                pos_display = " / ".join(position) if position else "미설정"
            else:
                pos_display = position or "미설정"

            tier_display = tier or "미설정"
            member_lines.append(f"<@{uid}> [{pos_display} | {tier_display}]")
    else:
        member_lines = [f"<@{uid}>" for uid in members.keys()]

    member_text = "\n".join(member_lines) if member_lines else "(아직 없음)"

    e = discord.Embed(
        title=f"🎮 {lobby['title']}",
        description=f"상태: **{status_kr}**\n맵: **{map_name}**\n정원: **{len(members)}/{cap}**\n시작시간: **{start_time}**",
        color=discord.Color.blurple(),
    )
    e.add_field(name="참가자", value=member_text, inline=False)
    e.set_footer(text=f"호스트: {lobby.get('host_name', '알 수 없음')}")
    return e


# ---------- 참가 선택(에페메럴) ----------
class JoinSelectionView(discord.ui.View):
    def __init__(self, lobby_message_id: int):
        super().__init__(timeout=180)
        self.lobby_message_id = lobby_message_id
        self.selected_tier: str | None = None
        self.selected_position: list[str] | None = None

        self.add_item(TierJoinSelect())
        self.add_item(PositionJoinSelect())

    def ready(self) -> bool:
        return self.selected_tier is not None and self.selected_position is not None

    async def _render(self, interaction: discord.Interaction):
        tier = self.selected_tier or "미설정"
        pos = self.selected_position or []
        pos_display = " / ".join(pos) if pos else "미설정"

        embed = discord.Embed(title="참가 정보 선택", color=discord.Color.gold())
        embed.add_field(name="티어", value=f"🔹 {tier}", inline=True)
        embed.add_field(name="포지션(1,2순위)", value=f"🛡️ {pos_display}", inline=True)
        embed.set_footer(text="선택 후 '참가'를 누르세요.")
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="join:confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = lobbies.get(self.lobby_message_id)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다(봇 재시작 등).", ephemeral=True)
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
        if not self.ready():
            await interaction.response.send_message("티어와 포지션을 모두 선택해 주세요.", ephemeral=True)
            return

        lobby["members"][uid] = {"position": self.selected_position, "tier": self.selected_tier}

        try:
            channel = interaction.channel
            lobby_msg = await channel.fetch_message(self.lobby_message_id)
            if len(lobby["members"]) >= lobby["capacity"]:
                lobby["status"] = "closed"
            await lobby_msg.edit(embed=lobby_embed(lobby), view=LobbyView.persistent())
        except Exception as e:
            print(f"Error updating lobby message on join: {e}")


class TierJoinSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="티어 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=t) for t in TIERS],
            custom_id="join:tier",
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, JoinSelectionView):
            view.selected_tier = self.values[0]
            await view._render(interaction)


class PositionJoinSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="포지션 선택 (1,2순위)",
            min_values=2,
            max_values=2,
            options=[discord.SelectOption(label=p) for p in POSITIONS],
            custom_id="join:pos",
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, JoinSelectionView):
            view.selected_position = list(self.values)
            await view._render(interaction)


# ---------- 로비 생성(에페메럴) ----------
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

        view = FinalizeLobbyView(lobby)
        await interaction.response.send_message("📍 맵과 시간을 선택한 뒤 '생성'을 누르세요.", view=view, ephemeral=True)


class MapSelectSimple(discord.ui.Select):
    def __init__(self, lobby: dict):
        self.lobby = lobby
        super().__init__(
            placeholder="맵 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=m, value=m) for m in MAPS],
            custom_id="finalize:map",
        )

    async def callback(self, interaction: discord.Interaction):
        self.lobby["map"] = self.values[0]
        await self.view.render(interaction)  # type: ignore


class HourSelectSimple(discord.ui.Select):
    def __init__(self, lobby: dict):
        self.lobby = lobby
        super().__init__(
            placeholder="시간 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=f"{h:02d}시", value=f"{h:02d}:00") for h in range(24)],
            custom_id="finalize:hour",
        )

    async def callback(self, interaction: discord.Interaction):
        self.lobby["start_time"] = self.values[0]
        await self.view.render(interaction)  # type: ignore


class FinalizeLobbyView(discord.ui.View):
    def __init__(self, lobby: dict):
        super().__init__(timeout=180)
        self.lobby = lobby
        self.add_item(MapSelectSimple(self.lobby))
        self.add_item(HourSelectSimple(self.lobby))

    async def render(self, interaction: discord.Interaction):
        map_name = self.lobby.get("map", "미설정")
        start_time = self.lobby.get("start_time", "미설정")
        color = discord.Color.green() if map_name != "미설정" and start_time != "미설정" else discord.Color.gold()
        embed = discord.Embed(title="로비 생성 설정", color=color)
        embed.add_field(name="맵", value=f"🔹 {map_name}", inline=True)
        embed.add_field(name="시작시간", value=f"🕒 {start_time}", inline=True)
        embed.set_footer(text="모두 선택한 뒤 '생성'을 누르세요.")
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    @discord.ui.button(label="생성", style=discord.ButtonStyle.success, custom_id="finalize:create")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.lobby.get("map") == "미설정" or self.lobby.get("start_time") == "미설정":
            await interaction.response.send_message("맵과 시작 시간을 모두 선택해야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        msg = await channel.send(embed=lobby_embed(self.lobby), view=LobbyView.persistent())
        lobbies[msg.id] = self.lobby


# ---------- 로비 메시지 버튼 (persistent) ----------
class LobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def persistent() -> "LobbyView":
        return LobbyView()

    def get_lobby(self, interaction: discord.Interaction) -> dict | None:
        if interaction.message is None:
            return None
        return lobbies.get(interaction.message.id)

    def is_host(self, interaction: discord.Interaction, lobby: dict) -> bool:
        return interaction.user.id == lobby["host_id"]

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="lobby:join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다(봇 재시작 등).", ephemeral=True)
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

        # 협곡이 아닌 경우: 반드시 defer로 즉시 ACK 후 편집
        if lobby.get("map") != "소환사의 협곡":
            await interaction.response.defer(ephemeral=True)

            # 저장은 빈 dict로 (표기 안함)
            lobby["members"][uid] = {}

            if len(lobby["members"]) >= lobby["capacity"]:
                lobby["status"] = "closed"

            try:
                await interaction.message.edit(embed=lobby_embed(lobby), view=LobbyView.persistent())
            except Exception as e:
                print(f"Error editing lobby message: {e}")

            await interaction.followup.send("✅ 참가가 완료되었습니다!", ephemeral=True)
            return

        # 협곡인 경우: 선택 UI
        view = JoinSelectionView(interaction.message.id)
        await interaction.response.send_message("티어와 포지션을 선택한 뒤 '참가'를 누르세요.", view=view, ephemeral=True)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, custom_id="lobby:leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다(봇 재시작 등).", ephemeral=True)
            return
        if lobby["status"] != "open":
            await interaction.response.send_message("마감/시작된 로비는 취소할 수 없습니다.", ephemeral=True)
            return

        uid = interaction.user.id
        if uid not in lobby["members"]:
            await interaction.response.send_message("참가 상태가 아닙니다.", ephemeral=True)
            return

        del lobby["members"][uid]
        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(embed=lobby_embed(lobby), view=LobbyView.persistent())
        await interaction.followup.send("✅ 참가가 취소되었습니다.", ephemeral=True)

    @discord.ui.button(label="마감", style=discord.ButtonStyle.danger, custom_id="lobby:close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다(봇 재시작 등).", ephemeral=True)
            return
        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 마감할 수 있습니다.", ephemeral=True)
            return
        if lobby["status"] != "open":
            await interaction.response.send_message("이미 마감/시작된 로비입니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        lobby["status"] = "closed"
        await interaction.message.edit(embed=lobby_embed(lobby), view=LobbyView.persistent())

    @discord.ui.button(label="시작", style=discord.ButtonStyle.primary, custom_id="lobby:start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다(봇 재시작 등).", ephemeral=True)
            return
        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 시작할 수 있습니다.", ephemeral=True)
            return
        if lobby["status"] == "started":
            await interaction.response.send_message("이미 시작된 로비입니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        lobby["status"] = "started"
        await interaction.message.edit(embed=lobby_embed(lobby), view=LobbyView.persistent())

    @discord.ui.button(label="내전 취소", style=discord.ButtonStyle.danger, custom_id="lobby:cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다(봇 재시작 등).", ephemeral=True)
            return
        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 취소할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        lobby["status"] = "cancelled"
        lobbies.pop(interaction.message.id, None)
        await interaction.message.edit(embed=lobby_embed(lobby), view=None)


# ---------- 로비 생성 패널(채널에 설치되는 버튼) ----------
class CreateLobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎮 내전 로비 생성", style=discord.ButtonStyle.blurple, custom_id="create_lobby_btn")
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreateLobbyModal())


def is_lobby_panel_message(msg: discord.Message) -> bool:
    if msg.author != client.user:
        return False
    if not msg.embeds:
        return False
    if msg.embeds[0].title != "🎮 롤 내전 로비":
        return False
    for row in msg.components:
        for comp in row.children:
            if getattr(comp, "custom_id", None) == "create_lobby_btn":
                return True
    return False


@client.event
async def on_ready():
    # persistent view 등록: 재시작 후에도 버튼 작동
    client.add_view(CreateLobbyView())
    client.add_view(LobbyView.persistent())

    print(f"Logged in as {client.user} (ID: {client.user.id})")

    # 패널 메시지 설치(없으면 생성)
    for guild in client.guilds:
        installed = False

        for channel in guild.text_channels:
            if not channel.permissions_for(guild.me).send_messages:
                continue

            try:
                async for msg in channel.history(limit=30):
                    if is_lobby_panel_message(msg):
                        installed = True
                        break
            except Exception:
                continue

            if installed:
                break

        if not installed:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    embed = discord.Embed(
                        title="🎮 롤 내전 로비",
                        description="아래 버튼을 클릭하여 로비를 생성하세요!",
                        color=discord.Color.blurple(),
                    )
                    await channel.send(embed=embed, view=CreateLobbyView())
                    installed = True
                    break


client.run(TOKEN)
