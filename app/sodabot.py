import os
import discord
from dotenv import load_dotenv
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path(os.getenv("DB_PATH", "bot.db"))
KST = timezone(timedelta(hours=9))

def db_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS lobbies (
            lobby_message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            host_name TEXT,
            title TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            map_name TEXT NOT NULL,
            start_at TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS lobby_members (
            lobby_message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            position1 TEXT,
            position2 TEXT,
            tier TEXT,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (lobby_message_id, user_id)
        )
        """)
        conn.commit()

def now_kst() -> datetime:
    return datetime.now(KST)

def iso_kst(dt: datetime) -> str:
    return dt.astimezone(KST).isoformat()

def compute_start_at_iso(hhmm: str) -> str:
    """
    사용자가 고른 HH:MM을 기준으로 KST 날짜를 계산
    - 이미 지난 시각이면 다음날로 설정
    """
    n = now_kst()
    hh, mm = map(int, hhmm.split(":"))
    candidate = n.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate < n:
        candidate = candidate + timedelta(days=1)
    return iso_kst(candidate)

def db_create_lobby(
    lobby_message_id: int,
    guild_id: int,
    channel_id: int,
    host_id: int,
    host_name: str,
    title: str,
    capacity: int,
    map_name: str,
    start_at_iso: str,
    status: str = "open",
):
    with db_connect() as conn:
        conn.execute("""
        INSERT INTO lobbies (
            lobby_message_id, guild_id, channel_id, host_id, host_name,
            title, capacity, map_name, start_at, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lobby_message_id, guild_id, channel_id, host_id, host_name,
            title, capacity, map_name, start_at_iso, status, iso_kst(now_kst())
        ))
        conn.commit()

def db_get_lobby(lobby_message_id: int) -> sqlite3.Row | None:
    with db_connect() as conn:
        cur = conn.execute("SELECT * FROM lobbies WHERE lobby_message_id = ?", (lobby_message_id,))
        return cur.fetchone()


def db_update_lobby_status(lobby_message_id: int, status: str):
    with db_connect() as conn:
        conn.execute("UPDATE lobbies SET status = ? WHERE lobby_message_id = ?", (status, lobby_message_id))
        conn.commit()


def db_count_members(lobby_message_id: int) -> int:
    with db_connect() as conn:
        cur = conn.execute("SELECT COUNT(*) AS c FROM lobby_members WHERE lobby_message_id = ?", (lobby_message_id,))
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def db_list_members(lobby_message_id: int) -> list[sqlite3.Row]:
    with db_connect() as conn:
        cur = conn.execute("""
            SELECT user_id, position1, position2, tier, joined_at
            FROM lobby_members
            WHERE lobby_message_id = ?
            ORDER BY joined_at ASC
        """, (lobby_message_id,))
        return cur.fetchall()


def db_add_member(
    lobby_message_id: int,
    user_id: int,
    position1: str | None,
    position2: str | None,
    tier: str | None,
):
    with db_connect() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO lobby_members (
            lobby_message_id, user_id, position1, position2, tier, joined_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (lobby_message_id, user_id, position1, position2, tier, iso_kst(now_kst())))
        conn.commit()


def db_remove_member(lobby_message_id: int, user_id: int) -> int:
    with db_connect() as conn:
        cur = conn.execute(
            "DELETE FROM lobby_members WHERE lobby_message_id = ? AND user_id = ?",
            (lobby_message_id, user_id),
        )
        conn.commit()
        return cur.rowcount


def db_is_member(lobby_message_id: int, user_id: int) -> bool:
    with db_connect() as conn:
        cur = conn.execute("""
            SELECT 1 FROM lobby_members WHERE lobby_message_id = ? AND user_id = ? LIMIT 1
        """, (lobby_message_id, user_id))
        return cur.fetchone() is not None


def db_list_active_lobbies() -> list[sqlite3.Row]:
    # 재시작 시 버튼/임베드 복구 대상
    with db_connect() as conn:
        cur = conn.execute("""
            SELECT * FROM lobbies
            WHERE status IN ('open','closed','started')
            ORDER BY created_at DESC
        """)
        return cur.fetchall()

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

# 시작 시간 옵션
TIME_OPTIONS = [f"{h:02d}" for h in range(24)]

def format_start_at(start_at_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(start_at_iso)
        days_kr = ["월", "화", "수", "목", "금", "토", "일"]
        day_name = days_kr[dt.weekday()]
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M") + f" ({day_name})"
    except Exception:
        return start_at_iso

def lobby_embed_from_db(lobby_row: sqlite3.Row) -> discord.Embed:
    cap = int(lobby_row["capacity"])
    status = lobby_row["status"]
    map_name = lobby_row["map_name"]
    start_at = lobby_row["start_at"]

    status_kr = {"open": "모집 중", "closed": "마감", "cancelled": "취소됨", "started": "시작됨"}.get(status, status)

    members = db_list_members(int(lobby_row["lobby_message_id"]))
    member_count = len(members)

    # 참가자 표기: 협곡만 포지션/티어 표시, 그 외는 멘션만
    lines: list[str] = []
    if map_name == "소환사의 협곡":
        for m in members:
            uid = int(m["user_id"])
            p1 = m["position1"]
            p2 = m["position2"]
            tier = m["tier"]
            pos = " / ".join([x for x in [p1, p2] if x]) if (p1 or p2) else "미설정"
            t = tier if tier else "미설정"
            lines.append(f"<@{uid}> [{pos} | {t}]")
    else:
        for m in members:
            uid = int(m["user_id"])
            lines.append(f"<@{uid}>")

    member_text = "\n".join(lines) if lines else "(아직 없음)"

    e = discord.Embed(
        title=f"🎮 {lobby_row['title']}",
        description=(
            f"상태: **{status_kr}**\n"
            f"맵: **{map_name}**\n"
            f"정원: **{member_count}/{cap}**\n"
            f"시작시간: **{format_start_at(start_at)}**"
        ),
        color=discord.Color.blurple(),
    )
    e.add_field(name="참가자", value=member_text, inline=False)
    try:
        host_name = lobby_row['host_name']
        if not host_name:
            host_name = f"<@{lobby_row['host_id']}>"
    except (KeyError, IndexError, TypeError):
        host_name = f"<@{lobby_row['host_id']}>"
    e.set_footer(text=f"호스트: {host_name}")
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
        lobby = db_get_lobby(self.lobby_message_id)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if lobby["status"] != "open":
            await interaction.response.send_message("이미 마감/시작된 로비입니다.", ephemeral=True)
            return

        uid = interaction.user.id
        if db_is_member(self.lobby_message_id, uid):
            await interaction.response.send_message("이미 참가하셨습니다.", ephemeral=True)
            return
        if db_count_members(self.lobby_message_id) >= int(lobby["capacity"]):
            await interaction.response.send_message("정원이 가득 찼습니다.", ephemeral=True)
            return
        if not self.ready():
            await interaction.response.send_message("티어와 포지션을 모두 선택해 주세요.", ephemeral=True)
            return

        p1, p2 = self.selected_position[0], self.selected_position[1]
        db_add_member(self.lobby_message_id, uid, p1, p2, self.selected_tier)

        # 마감 체크
        if db_count_members(self.lobby_message_id) >= int(lobby["capacity"]):
            db_update_lobby_status(self.lobby_message_id, "closed")

        # 로비 메시지 갱신
        await interaction.response.defer(ephemeral=True)
        try:
            if interaction.channel:
                msg = await interaction.channel.fetch_message(self.lobby_message_id)
                await msg.edit(embed=lobby_embed_from_db(db_get_lobby(self.lobby_message_id)), view=LobbyView.persistent())
        except Exception as e:
            print(f"Error updating lobby message on join: {e}")


class TierJoinSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="티어 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=t, value=t) for t in TIERS],
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

        draft = {
            "title": str(self.제목.value),
            "capacity": capacity,
            "map_name": "미설정",
            "start_hhmm": "미설정",
        }

        view = FinalizeLobbyView(draft)
        await interaction.response.send_message("📍 맵과 시간을 선택한 뒤 '생성'을 누르세요.", view=view, ephemeral=True)


class MapSelectSimple(discord.ui.Select):
    def __init__(self, draft: dict):
        self.draft = draft
        super().__init__(
            placeholder="맵 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=m, value=m) for m in MAPS],
            custom_id="finalize:map",
        )

    async def callback(self, interaction: discord.Interaction):
        self.draft["map"] = self.values[0]
        await self.view.render(interaction)  # type: ignore


class TimeSelectSimple(discord.ui.Select):
    def __init__(self, draft: dict):
        self.draft = draft
        super().__init__(
            placeholder="시작 시간 선택",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=t, value=t) for t in TIME_OPTIONS],
            custom_id="finalize:time",
        )


    async def callback(self, interaction: discord.Interaction):
        self.draft["start_time"] = f"{self.values[0]}:00"
        await self.view.render(interaction)  # type: ignore


class FinalizeLobbyView(discord.ui.View):
    def __init__(self, draft: dict):
        super().__init__(timeout=180)
        self.draft = draft
        self.add_item(MapSelectSimple(self.draft))
        self.add_item(TimeSelectSimple(self.draft))

    async def render(self, interaction: discord.Interaction):
        map_name = self.draft.get("map", "미설정")
        start_time = self.draft.get("start_time", "미설정")
        ok = (map_name != "미설정" and start_time != "미설정")
        color = discord.Color.green() if ok else discord.Color.gold()
        embed = discord.Embed(title="로비 생성 설정", color=color)
        embed.add_field(name="맵", value=f"🔹 {map_name}", inline=True)
        embed.add_field(name="시작시간", value=f"🕒 {start_time}", inline=True)
        embed.set_footer(text="모두 선택한 뒤 '생성'을 누르세요.")
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    @discord.ui.button(label="생성", style=discord.ButtonStyle.success, custom_id="finalize:create")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        map_name = self.draft.get("map", "미설정")
        start_time = self.draft.get("start_time", "미설정")
        if map_name == "미설정" or start_time == "미설정":
            await interaction.response.send_message("맵과 시작 시간을 모두 선택해야 합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        start_at_iso = compute_start_at_iso(start_time)

        # 채널에 로비 메시지 전송 후 message_id로 DB 저장
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send("채널 정보를 확인할 수 없습니다.", ephemeral=True)
            return
        
        # 임베드 생성은 DB row 기반이라, 먼저 메시지 ID를 확보하고 DB insert 후 fetch하여 embed 생성
        temp_embed = discord.Embed(title="로비 생성 중...", color=discord.Color.blurple())
        msg = await channel.send(embed=temp_embed, view=LobbyView.persistent())

        db_create_lobby(
            lobby_message_id=msg.id,
            guild_id=interaction.guild_id or 0,
            channel_id=interaction.channel_id or 0,
            host_id=interaction.user.id,
            host_name=interaction.user.display_name or interaction.user.name or str(interaction.user.id),
            title=self.draft["title"],
            capacity=int(self.draft["capacity"]),
            map_name=map_name,
            start_at_iso=start_at_iso,
            status="open",
        )

        lobby = db_get_lobby(msg.id)
        await msg.edit(embed=lobby_embed_from_db(lobby), view=LobbyView.persistent())


# ---------- 로비 메시지 버튼 (persistent) ----------
class LobbyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def persistent() -> "LobbyView":
        return LobbyView()

    def get_lobby(self, interaction: discord.Interaction) -> sqlite3.Row | None:
        if interaction.message is None:
            return None
        return db_get_lobby(interaction.message.id)

    def is_host(self, interaction: discord.Interaction, lobby: sqlite3.Row) -> bool:
        return interaction.user.id == int(lobby["host_id"])

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="lobby:join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if lobby["status"] != "open":
            await interaction.response.send_message("이미 마감/시작된 로비입니다.", ephemeral=True)
            return

        lobby_id = int(lobby["lobby_message_id"])
        uid = interaction.user.id

        if db_is_member(lobby_id, uid):
            await interaction.response.send_message("이미 참가하셨습니다.", ephemeral=True)
            return

        if db_count_members(lobby_id) >= int(lobby["capacity"]):
            await interaction.response.send_message("정원이 가득 찼습니다.", ephemeral=True)
            return

        # 협곡이 아닌 경우: 포지션/티어 저장하지 않음(NULL)
        if lobby["map_name"] != "소환사의 협곡":
            await interaction.response.defer(ephemeral=True)

            db_add_member(lobby_id, uid, None, None, None)
            # 마감 체크
            if db_count_members(lobby_id) >= int(lobby["capacity"]):
                db_update_lobby_status(lobby_id, "closed")

            # 메시지 갱신
            try:
                await interaction.message.edit(embed=lobby_embed_from_db(db_get_lobby(lobby_id)), view=LobbyView.persistent())
            except Exception as e:
                print(f"Error editing lobby message: {e}")
            return

        # 협곡인 경우: 선택 UI
        view = JoinSelectionView(lobby_id)
        await interaction.response.send_message("티어와 포지션을 선택한 뒤 '참가'를 누르세요.", view=view, ephemeral=True)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, custom_id="lobby:leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if lobby["status"] != "open":
            await interaction.response.send_message("마감/시작된 로비는 취소할 수 없습니다.", ephemeral=True)
            return

        lobby_id = int(lobby["lobby_message_id"])
        uid = interaction.user.id

        if not db_is_member(lobby_id, uid):
            await interaction.response.send_message("참가 상태가 아닙니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        db_remove_member(lobby_id, uid)

        await interaction.message.edit(embed=lobby_embed_from_db(db_get_lobby(lobby_id)), view=LobbyView.persistent())

    @discord.ui.button(label="마감", style=discord.ButtonStyle.danger, custom_id="lobby:close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 마감할 수 있습니다.", ephemeral=True)
            return
        if lobby["status"] != "open":
            await interaction.response.send_message("이미 마감/시작된 로비입니다.", ephemeral=True)
            return

        lobby_id = int(lobby["lobby_message_id"])

        await interaction.response.defer(ephemeral=True)
        db_update_lobby_status(lobby_id, "closed")
        await interaction.message.edit(embed=lobby_embed_from_db(db_get_lobby(lobby_id)), view=LobbyView.persistent())

    @discord.ui.button(label="시작", style=discord.ButtonStyle.primary, custom_id="lobby:start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 시작할 수 있습니다.", ephemeral=True)
            return
        if lobby["status"] == "started":
            await interaction.response.send_message("이미 시작된 로비입니다.", ephemeral=True)
            return

        lobby_id = int(lobby["lobby_message_id"])

        await interaction.response.defer(ephemeral=True)
        db_update_lobby_status(lobby_id, "started")
        await interaction.message.edit(embed=lobby_embed_from_db(db_get_lobby(lobby_id)), view=LobbyView.persistent())

    @discord.ui.button(label="내전 취소", style=discord.ButtonStyle.danger, custom_id="lobby:cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = self.get_lobby(interaction)
        if not lobby:
            await interaction.response.send_message("로비 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        if not self.is_host(interaction, lobby):
            await interaction.response.send_message("호스트만 취소할 수 있습니다.", ephemeral=True)
            return

        lobby_id = int(lobby["lobby_message_id"])

        await interaction.response.defer(ephemeral=True)
        db_update_lobby_status(lobby_id, "cancelled")

        # 메시지 버튼 제거
        await interaction.message.edit(embed=lobby_embed_from_db(db_get_lobby(lobby_id)), view=None)


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


async def install_panel_if_missing():
    # 서버 1개 기준: 첫 guild에만 설치
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

        break

async def restore_lobbies_on_start():
    # 재시작 시 DB 기반으로 로비 메시지에 View 재부착 + 임베드 최신화
    for lobby in db_list_active_lobbies():
        lobby_id = int(lobby["lobby_message_id"])
        channel_id = int(lobby["channel_id"])

        channel = client.get_channel(channel_id)
        if channel is None:
            continue

        try:
            msg = await channel.fetch_message(lobby_id)
        except Exception:
            continue

        # cancelled이면 view 제거(남아있을 경우)
        if lobby["status"] == "cancelled":
            try:
                await msg.edit(embed=lobby_embed_from_db(lobby), view=None)
            except Exception:
                pass
            continue

        try:
            await msg.edit(embed=lobby_embed_from_db(db_get_lobby(lobby_id)), view=LobbyView.persistent())
        except Exception:
            pass


@client.event
async def on_ready():
    init_db()

    # persistent view 등록
    client.add_view(CreateLobbyView())
    client.add_view(LobbyView.persistent())

    print(f"Logged in as {client.user} (ID: {client.user.id})")

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print(f"DB_PATH = {DB_PATH.resolve()}")

    await install_panel_if_missing()
    await restore_lobbies_on_start()


client.run(TOKEN)
