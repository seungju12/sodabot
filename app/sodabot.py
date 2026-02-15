import os
import discord
from dotenv import load_dotenv
import sqlite3
from pathlib import Path
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from typing import Mapping, Any

# ================================
# 환경 설정 및 초기화
# ================================
load_dotenv()  # .env 파일에서 환경변수 로드

# DB 경로: 기본값 "bot.db", 환경변수로 커스텀 가능
DB_PATH = Path(os.getenv("DB_PATH", "bot.db"))

# 포럼 채널 ID: 내전 기록을 별도의 포럼에 저장할 때 사용
FORUM_CHANNEL_ID = int(os.getenv("FORUM_CHANNEL_ID", "0")) if os.getenv("FORUM_CHANNEL_ID") else None

# 로비 패널 채널 ID: 모집 중인 로비 목록 표시 채널 (미설정 시 아무 채널이나 사용)
LOBBY_PANEL_CHANNEL_ID = int(os.getenv("LOBBY_PANEL_CHANNEL_ID", "0")) if os.getenv("LOBBY_PANEL_CHANNEL_ID") else None

# 로비 생성 시 첨부하는 이미지 파일 경로
IMAGE_PATH = Path(__file__).parent / "image" / "IMG_2155.gif"

# KST 타임존 (한국 시간)
KST = timezone(timedelta(hours=9))

# ================================
# 데이터베이스 연결 및 초기화
# ================================
def db_connect() -> sqlite3.Connection:
    """DB 연결 객체 반환
    - 디렉토리 자동 생성
    - Row 객체를 딕셔너리처럼 사용 가능
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 쿼리 결과를 dict 형태로 사용
    return conn

def init_db():
    """DB 테이블 초기화 (이미 존재하면 생성 안 함)
    테이블 구조:
    - lobbies: 생성된 로비 정보
    - lobby_members: 각 로비의 참가자 정보
    """
    with db_connect() as conn:
        # 로비 정보 저장
        conn.execute("""
        CREATE TABLE IF NOT EXISTS lobbies (
            lobby_message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            forum_post_id INTEGER,
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

# ================================
# 시간 관련 유틸리티 함수
# ================================
def now_kst() -> datetime:
    """현재 시간을 KST 기준으로 반환"""
    return datetime.now(KST)

def format_date_with_day(dt: datetime) -> str:
    """날짜를 "2026-02-12 (목)" 포맷으로 포매팅
    
    Args:
        dt: 변환할 datetime 객체
    
    Returns:
        "YYYY-MM-DD (요일)" 형식의 문자열
    """
    days = ['월', '화', '수', '목', '금', '토', '일']
    day_of_week = days[dt.weekday()]
    return dt.strftime(f'%Y-%m-%d ({day_of_week})')

def iso_kst(dt: datetime) -> str:
    """datetime을 ISO 8601 형식 문자열로 변환 (KST 기준)
    
    DB 저장 및 재조회 시 사용
    """
    return dt.astimezone(KST).isoformat()

def compute_start_at_iso(hhmm: str) -> str:
    """사용자가 입력한 시간(HH:MM)을 ISO 형식으로 변환
    
    로직: 현재 시간보다 이미 지난 시각이면 다음날로 자동 조정
    예) 현재 15:00이고 사용자가 14:00 선택 → 내일 14:00으로 설정
    
    Args:
        hhmm: "HH:MM" 형식의 시간 문자열
    
    Returns:
        ISO 8601 형식의 datetime 문자열
    """
    n = now_kst()
    hh, mm = map(int, hhmm.split(":"))
    candidate = n.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate < n:
        candidate = candidate + timedelta(days=1)
    return iso_kst(candidate)

# ================================
# 데이터베이스 로비 CRUD 함수
# ================================
def db_create_lobby(
    lobby_message_id: int,  # Discord 메시지 ID (로비 식별자)
    guild_id: int,  # Discord 서버 ID
    channel_id: int,  # 메시지가 있는 채널 ID (포럼 스레드 ID일 수도 있음)
    host_id: int,  # 로비 생성자의 사용자 ID
    host_name: str,  # 생성자 닉네임
    title: str,  # 로비 제목
    capacity: int,  # 모집 정원
    map_name: str,  # 게임 맵 이름
    start_at_iso: str,  # ISO 형식 시작 시간
    forum_post_id: int | None = None,  # 포럼 채널 사용 시 스레드 ID
    status: str = "open",  # 로비 상태 (open/closed/started/cancelled)
):
    with db_connect() as conn:
        conn.execute("""
        INSERT INTO lobbies (
            lobby_message_id, guild_id, channel_id, forum_post_id, host_id, host_name,
            title, capacity, map_name, start_at, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lobby_message_id, guild_id, channel_id, forum_post_id, host_id, host_name,
            title, capacity, map_name, start_at_iso, status, iso_kst(now_kst())
        ))
        conn.commit()

def db_get_lobby(lobby_message_id: int) -> sqlite3.Row | None:
    """메시지 ID로 로비 정보 조회"""
    with db_connect() as conn:
        cur = conn.execute("SELECT * FROM lobbies WHERE lobby_message_id = ?", (lobby_message_id,))
        return cur.fetchone()

def db_update_lobby_status(lobby_message_id: int, status: str):
    """로비 상태 업데이트 (open → closed → started → cancelled)"""
    with db_connect() as conn:
        conn.execute("UPDATE lobbies SET status = ? WHERE lobby_message_id = ?", (status, lobby_message_id))
        conn.commit()

def db_count_members(lobby_message_id: int) -> int:
    """해당 로비의 현재 참가자 수 조회"""
    with db_connect() as conn:
        cur = conn.execute("SELECT COUNT(*) AS c FROM lobby_members WHERE lobby_message_id = ?", (lobby_message_id,))
        row = cur.fetchone()
        return int(row["c"]) if row else 0

def db_list_members(lobby_message_id: int) -> list[sqlite3.Row]:
    """해당 로비의 모든 참가자 목록 조회 (참가 순서대로)"""
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
    """참가자 정보 저장 (이미 존재하면 업데이트)"""
    with db_connect() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO lobby_members (
            lobby_message_id, user_id, position1, position2, tier, joined_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (lobby_message_id, user_id, position1, position2, tier, iso_kst(now_kst())))
        conn.commit()

def db_try_add_member(
    lobby_message_id: int,
    user_id: int,
    position1: str | None,
    position2: str | None,
    tier: str | None,
    capacity: int,
) -> tuple[str, int]:
    """참가 시도 (원자성 보장: 다중 참가 or 정원초과 방지)
    
    Returns:
        (상태, 현재인원수) 튜플
        - 상태: "added" (성공) | "already" (이미 참가) | "full" (정원 다참)
    """
    with db_connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        cur = conn.execute(
            "SELECT 1 FROM lobby_members WHERE lobby_message_id = ? AND user_id = ? LIMIT 1",
            (lobby_message_id, user_id),
        )
        if cur.fetchone() is not None:
            conn.rollback()
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM lobby_members WHERE lobby_message_id = ?",
                (lobby_message_id,),
            )
            row = cur.fetchone()
            return "already", int(row["c"]) if row else 0

        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM lobby_members WHERE lobby_message_id = ?",
            (lobby_message_id,),
        )
        row = cur.fetchone()
        current_count = int(row["c"]) if row else 0
        if current_count >= capacity:
            conn.rollback()
            return "full", current_count

        conn.execute(
            """
            INSERT INTO lobby_members (
                lobby_message_id, user_id, position1, position2, tier, joined_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (lobby_message_id, user_id, position1, position2, tier, iso_kst(now_kst())),
        )
        conn.commit()
        return "added", current_count + 1


def db_remove_member(lobby_message_id: int, user_id: int) -> int:
    """참가자 제거 (참가 취소)
    
    Returns:
        삭제된 행 수 (0 or 1)
    """
    with db_connect() as conn:
        cur = conn.execute(
            "DELETE FROM lobby_members WHERE lobby_message_id = ? AND user_id = ?",
            (lobby_message_id, user_id),
        )
        conn.commit()
        return cur.rowcount

def db_is_member(lobby_message_id: int, user_id: int) -> bool:
    """사용자가 해당 로비에 참가했는지 확인"""
    with db_connect() as conn:
        cur = conn.execute("""
            SELECT 1 FROM lobby_members WHERE lobby_message_id = ? AND user_id = ? LIMIT 1
        """, (lobby_message_id, user_id))
        return cur.fetchone() is not None

def db_list_active_lobbies() -> list[sqlite3.Row]:
    """활성 로비 목록 (진행 중인 로비)
    - open: 모집 중
    - closed: 정원 마감
    - started: 게임 시작됨
    (cancelled 제외)
    """
    with db_connect() as conn:
        cur = conn.execute("""
            SELECT * FROM lobbies
            WHERE status IN ('open','closed','started')
            ORDER BY created_at DESC
        """)
        return cur.fetchall()

def db_list_open_lobbies() -> list[sqlite3.Row]:
    """모집 중인 로비만 조회 (패널에 표시)"""
    with db_connect() as conn:
        cur = conn.execute("""
            SELECT * FROM lobbies
            WHERE status = 'open'
            ORDER BY created_at DESC
        """)
        return cur.fetchall()

def db_list_all_lobbies() -> list[sqlite3.Row]:
    """모든 로비 조회 (초기화 시 대상)"""
    with db_connect() as conn:
        cur = conn.execute("""
            SELECT * FROM lobbies
            ORDER BY created_at DESC
        """)
        return cur.fetchall()

def db_clear_all_members():
    """모든 참가자 정보 삭제 (초기화 명령어 시 호출)"""
    with db_connect() as conn:
        conn.execute("DELETE FROM lobby_members")
        conn.commit()

# ================================
# Discord 봇 초기화
# ================================
TOKEN = os.getenv("DISCORD_TOKEN")  # .env에서 봇 토큰 로드

# 필요한 권한 설정
intents = discord.Intents.default()
intents.guilds = True  # 서버 이벤트
intents.message_content = True  # 메시지 내용 읽기

client = discord.Client(intents=intents)  # Discord 봇 클라이언트
tree = discord.app_commands.CommandTree(client)  # 슬래시 명령어 등록용

lobbies: dict[int, dict] = {}  # 메모리 캐시 (현재 미사용)

# ================================
# 게임 데이터 상수
# ================================
POSITIONS = ["탑", "정글", "미드", "원딜", "서포터"]  # 롤 포지션 목록
TIERS = ["아이언", "브론즈", "실버", "골드", "플래티넘", "에메랄드", "다이아", "마스터", "마스터+300", "그랜드마스터", "챌린저"]  # 티어 목록
MAPS = ["소환사의 협곡", "무작위 총력전", "무작위 총력전: 아수라장"]  # 게임 모드

# ================================
# 파일 및 UI 상수
# ================================
def get_image_file() -> discord.File:
    """로비 생성 시 포럼/채널에 첨부할 이미지 파일 로드
    
    Raises:
        FileNotFoundError: 이미지 파일이 없으면 예외 발생
    """
    if IMAGE_PATH.exists():
        return discord.File(IMAGE_PATH, filename="lobby_image.gif")
    raise FileNotFoundError(f"이미지 파일을 찾을 수 없음: {IMAGE_PATH}")

# 시간 선택 UI에 표시할 옵션 (00:00 ~ 23:00)
TIME_OPTIONS = [f"{h:02d}" for h in range(24)]

# ================================
# 포매팅 유틸리티
# ================================
def format_start_at(start_at_iso: str) -> str:
    """ISO 형식 시간을 사용자 친화적으로 변환 ("2026-02-15 14:30 (일)")
    
    로비 메시지와 안내에서 표시할 때 사용
    """
    try:
        dt = datetime.fromisoformat(start_at_iso)
        days_kr = ["월", "화", "수", "목", "금", "토", "일"]
        day_name = days_kr[dt.weekday()]
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M") + f" ({day_name})"
    except Exception:
        return start_at_iso

def format_forum_title(map_name: str, start_at_iso: str, title: str) -> str:
    """포럼 스레드 제목을 게임 맵과 시간에 맞춰 생성
    
    예: 협곡 → "💜02/15 14:30 협곡내전💜"
    예: 칼바람 → "⚔️02/15 14:30 칼바람 내전⚔️"
    """
    try:
        dt = datetime.fromisoformat(start_at_iso).astimezone(KST)
        time_str = dt.strftime("%m/%d %H:%M")
        
        if map_name == "소환사의 협곡":
            return f"💜{time_str} 협곡내전💜"
        elif map_name == "무작위 총력전":
            return f"⚔️{time_str} 칼바람 내전⚔️"
        elif map_name == "무작위 총력전: 아수라장":
            return f"⚔️{time_str} 칼수라 내전⚔️"
        else:
            return f"🎮{time_str} {title}"
    except Exception:
        return title

# ================================
# 로비 임베드 빌더
# ================================
def lobby_embed_from_db(lobby_row: sqlite3.Row) -> discord.Embed:
    """DB의 로비 정보를 Discord 임베드로 변환
    
    표시 내용: 상태, 정원, 참가자 목록, 맵, 시작시간, 호스트
    
    협곡 vs 칼바람 구분:
    - 협곡(소환사의 협곡): 포지션/티어 표시
    - 칼바람/칼수라: 참가자 이름만 표시 (포지션 선택 X)
    """
    cap = int(lobby_row["capacity"])
    status = lobby_row["status"]
    map_name = lobby_row["map_name"]
    start_at = lobby_row["start_at"]

    # 상태 텍스트 및 이모지 매핑
    status_kr = {"open": "모집 중", "closed": "마감", "cancelled": "취소됨", "started": "시작됨"}.get(status, status)
    status_emoji = {"open": "🟢", "closed": "🔴", "cancelled": "⚫", "started": "🟡"}.get(status, "⚪")

    members = db_list_members(int(lobby_row["lobby_message_id"]))
    member_count = len(members)

    # 참가자 목록 구성: 협곡은 포지션/티어 포함, 칼바람은 이름만
    lines: list[str] = []
    if map_name == "소환사의 협곡":
        for idx, m in enumerate(members, start=1):
            uid = int(m["user_id"])
            p1 = m["position1"]
            p2 = m["position2"]
            tier = m["tier"]
            pos = " / ".join([x for x in [p1, p2] if x]) if (p1 or p2) else "미설정"
            t = tier if tier else "미설정"
            lines.append(f"{idx}. <@{uid}> | {pos} | {t}")
    else:
        for idx, m in enumerate(members, start=1):
            uid = int(m["user_id"])
            lines.append(f"{idx}. <@{uid}>")

    member_text = "*(아직 없음)*"
    if lines:
        max_value_len = 1000
        shown: list[str] = []
        for line in lines:
            next_value = "\n".join(shown + [line])
            if len(next_value) > max_value_len:
                break
            shown.append(line)

        remaining = len(lines) - len(shown)
        if remaining > 0:
            shown.append(f"...외 {remaining}명")
        member_text = "\n".join(shown)

    e = discord.Embed(
        title=f"{lobby_row['title']}",
        description="로비 정보",
        color=discord.Color.blurple(),
    )
    
    # 상태 (풀 너비)
    e.add_field(
        name=f"{status_emoji} 상태",
        value=f"{status_kr}",
        inline=False
    )
    
    # 정원 (풀 너비)
    e.add_field(
        name="👥 정원",
        value=f"{member_count} / {cap}",
        inline=False
    )
    
    # 맵 (풀 너비)
    e.add_field(
        name="🗺️ 맵",
        value=map_name,
        inline=False
    )
    
    # 시작시간 (풀 너비)
    e.add_field(
        name="🕒 시작시간",
        value=format_start_at(start_at),
        inline=False
    )
    
    # 참가자 (풀 너비)
    e.add_field(
        name="🎯 참가자 목록",
        value=member_text,
        inline=False
    )
    
    try:
        host_name = lobby_row['host_name']
        if not host_name:
            host_name = f"<@{lobby_row['host_id']}>"
    except (KeyError, IndexError, TypeError):
        host_name = f"<@{lobby_row['host_id']}>"
    
    e.set_footer(text=f"👑 호스트: {host_name}")
    return e


async def send_ephemeral_and_delete(interaction: discord.Interaction, content: str = None, delay: int = 5, **kwargs):
    """Ephemeral 메시지를 전송하고 `delay`초 후에 자동 삭제합니다.
    - 만약 interaction.response가 이미 사용되었다면 followup으로 전송합니다.
    - `view=` 같이 유저 상호작용 UI가 포함된 응답은 삭제하면 안 되므로 사용하지 마세요.
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(content, ephemeral=True, **kwargs)
            await asyncio.sleep(delay)
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
        else:
            msg = await interaction.followup.send(content, ephemeral=True, **kwargs)
            await asyncio.sleep(delay)
            try:
                await msg.delete()
            except Exception:
                pass
    except Exception as e:
        print(f"Error sending ephemeral autodelete: {e}")


async def send_ephemeral_get_deleter(interaction: discord.Interaction, content: str = None, **kwargs):
    """임시 메시지를 전송하고 나중에 삭제할 수 있는 함수 반환
    
    용도: 로비 생성 중 "처리 중..." 메시지 표시 → 완료 후 삭제
    
    사용 예:
        deleter = await send_ephemeral_get_deleter(interaction, "처리 중...")
        # 처리 수행...
        await deleter()  # 삭제
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(content, ephemeral=True, **kwargs)

            async def _deleter():
                try:
                    await interaction.delete_original_response()
                except Exception:
                    pass

            return _deleter
        else:
            msg = await interaction.followup.send(content, ephemeral=True, **kwargs)

            async def _deleter2():
                try:
                    await msg.delete()
                except Exception:
                    pass

            return _deleter2
    except Exception as e:
        print(f"Error sending ephemeral get deleter: {e}")

    async def _noop():
        return

    return _noop


# ================================
# Discord UI 컴포넌트
# ================================

# ▼ 협곡 로비 참가 시 포지션/티어 선택 UI
class JoinSelectionView(discord.ui.View):
    """협곡 로비 참가 시 포지션/티어 선택 UI
    
    구성:
    - TierJoinSelect: 티어 선택 드롭다운
    - PositionJoinSelect: 포지션 1,2순위 선택
    - 참가 버튼
    
    timeout=180: 3분 후 자동 비활성화
    """
    def __init__(self, lobby_message_id: int):
        super().__init__(timeout=180)
        self.lobby_message_id = lobby_message_id
        self.selected_tier: str | None = None
        self.selected_position: list[str] | None = None

        self.add_item(TierJoinSelect())
        self.add_item(PositionJoinSelect())

    def ready(self) -> bool:
        """티어와 포지션이 모두 선택되었는지 확인"""
        return self.selected_tier is not None and self.selected_position is not None

    async def _render(self, interaction: discord.Interaction):
        """선택한 정보를 임베드로 표시 (즉시 업데이트)"""
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
            await send_ephemeral_and_delete(interaction, "로비 정보를 찾을 수 없습니다.")
            return
        if lobby["status"] != "open":
            await send_ephemeral_and_delete(interaction, "이미 마감/시작된 로비입니다.")
            return

        uid = interaction.user.id
        if not self.ready():
            await send_ephemeral_and_delete(interaction, "티어와 포지션을 모두 선택해야 함")
            return

        p1, p2 = self.selected_position[0], self.selected_position[1]
        add_status, member_count = db_try_add_member(
            self.lobby_message_id,
            uid,
            p1,
            p2,
            self.selected_tier,
            int(lobby["capacity"]),
        )
        if add_status == "already":
            await send_ephemeral_and_delete(interaction, "이미 참가되었습니다.")
            return
        if add_status == "full":
            await send_ephemeral_and_delete(interaction, "정원이 가득 참")
            return

        # 마감 체크
        if member_count >= int(lobby["capacity"]):
            db_update_lobby_status(self.lobby_message_id, "closed")

        # 로비 메시지 갱신 (멘션 포함)
        await interaction.response.defer(ephemeral=True)
        deleter = await send_ephemeral_get_deleter(interaction, "참가 처리 중...")
        try:
            if interaction.channel:
                msg = await interaction.channel.fetch_message(self.lobby_message_id)
                # 현재 모든 멤버의 멘션을 포함
                current_members = db_list_members(self.lobby_message_id)
                member_mentions = " ".join([f"<@{int(m['user_id'])}>" for m in current_members])
                await msg.edit(
                    content=member_mentions if member_mentions else None,
                    embed=lobby_embed_from_db(db_get_lobby(self.lobby_message_id)),
                    view=LobbyView.persistent()
                )
        except Exception as e:
            print(f"Error updating lobby message on join: {e}")
        try:
            await update_lobby_panel()
        except Exception:
            pass
        finally:
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
            try:
                await deleter()
            except Exception:
                pass
        
        # 참가 완료 안내 메시지 (ephemeral - 나만 봄)
        try:
            start_at_str = lobby["start_at"]
            start_time_formatted = format_start_at(start_at_str)
            
            join_msg = f"✅ **내전 참가가 확인되었습니다!**\n\n"
            join_msg += f"🕐 **시작 시간:** {start_time_formatted}\n\n"
            join_msg += f"⏰ **내전 규칙 확인해주시고 시작 10분 전까지 꼭 모여주세요!**"
            
            await interaction.followup.send(join_msg, ephemeral=True)
        except Exception as e:
            print(f"[ERROR] 참가 안내 메시지 전송 실패: {e}")


class TierJoinSelect(discord.ui.Select):
    """참가 시 티어 선택 드롭다운"""
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
    """참가 시 포지션 1,2순위 선택 드롭다운"""
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


# ▼ 로비 생성 모달 (제목, 정원 입력)
class CreateLobbyModal(discord.ui.Modal, title="내전 로비 생성"):
    """로비 생성 시 사용자 입력받는 모달
    
    입력 항목:
    - 정원: 모집할 사람 수 (2-20명)
    - 포럼제목: 로비 이름 (선택, 비우면 자동 생성)
    """
    정원 = discord.ui.TextInput(label="모집 인원", placeholder="예: 10", default="10")
    포럼제목 = discord.ui.TextInput(
        label="포럼/로비 제목 (선택사항)",
        placeholder="비워놓으면 자동 생성됨. 예: 💜협곡 내전💜",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            capacity = int(self.정원.value)
        except ValueError:
            await send_ephemeral_and_delete(interaction, "정원은 숫자여야 합니다.")
            return

        if capacity < 2 or capacity > 20:
            await send_ephemeral_and_delete(interaction, "정원은 2~20 사이로 설정해 주세요.")
            return

        draft = {
            "capacity": capacity,
            "map_name": "미설정",
            "forum_title": str(self.포럼제목.value) if self.포럼제목.value else None,
        }

        # 맵 선택 View 생성
        view = discord.ui.View(timeout=300)
        view.add_item(MapSelectSimple(draft))
        
        embed = discord.Embed(
            title="🗺️ 맵 선택",
            description="로비에서 사용할 맵을 선택하세요.",
            color=discord.Color.blurple(),
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class MapSelectSimple(discord.ui.Select):
    """게임 맵 선택 드롭다운"""
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
        
        # defer 및 원본 메시지 삭제
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()
        
        # 맵 선택 후 캘린더 show
        view = CalendarSelectView(self.draft)
        await view.render_calendar(interaction)


class TimeSelect(discord.ui.Select):
    """시간 선택 드롭다운 (0:00 - 23:00)"""
    def __init__(self, draft: dict, selected_date):
        self.draft = draft
        self.selected_date = selected_date
        
        options = [discord.SelectOption(label=f"{h:02d}:00", value=f"{h:02d}:00") for h in range(0, 24)]
        super().__init__(
            placeholder="🕒 시간을 선택",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="select_time",
        )
    
    async def callback(self, interaction: discord.Interaction):
        self.draft["selected_date"] = self.selected_date
        self.draft["start_time"] = self.values[0]
        
        # defer 및 원본 메시지 삭제
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()
        
        # 최종 확인 단계
        embed = discord.Embed(
            title="✅ 생성 준비 완료",
            color=discord.Color.green(),
        )
        embed.add_field(name="맵", value=f"**{self.draft.get('map', '미설정')}**", inline=False)
        embed.add_field(name="날짜 & 시간", value=f"**{format_date_with_day(self.selected_date)} {self.values[0]}**", inline=False)
        embed.add_field(name="정원", value=f"**{self.draft.get('capacity', '?')}명**", inline=False)
        
        finalize_view = discord.ui.View(timeout=300)
        finalize_btn = discord.ui.Button(label="✅ 로비 생성", style=discord.ButtonStyle.success)
        
        async def create_callback(inter):
            await inter.response.defer(ephemeral=True)
            await inter.delete_original_response()
            await create_lobby_from_draft(inter, self.draft, already_deferred=True)
        
        finalize_btn.callback = create_callback
        finalize_view.add_item(finalize_btn)
        
        await interaction.followup.send(embed=embed, view=finalize_view, ephemeral=True)


class DateSelect1(discord.ui.Select):
    """날짜 선택 (1-15일)"""
    def __init__(self, draft: dict, year: int, month: int):
        """1-15일을 선택하는 드롭다운"""
        self.draft = draft
        self.year = year
        self.month = month
        
        options = [discord.SelectOption(label=f"{day}일", value=str(day)) for day in range(1, 16)]
        
        super().__init__(
            placeholder="📅 1-15일 중 선택",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="select_date_1",
        )
    
    async def callback(self, interaction: discord.Interaction):
        day = int(self.values[0])
        selected_date = now_kst().replace(year=self.year, month=self.month, day=day, hour=0, minute=0, second=0, microsecond=0)
        
        # defer 및 원본 메시지 삭제
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()
        
        embed = discord.Embed(
            title="🕒 시간 선택",
            description=f"**{format_date_with_day(selected_date)}** 에서 시작 시간을 선택하세요.",
            color=discord.Color.blurple(),
        )
        
        time_view = discord.ui.View(timeout=300)
        time_view.add_item(TimeSelect(self.draft, selected_date))
        
        await interaction.followup.send(embed=embed, view=time_view, ephemeral=True)


class DateSelect2(discord.ui.Select):
    """날짜 선택 (16-31일)"""
    def __init__(self, draft: dict, year: int, month: int):
        """16-31일을 선택하는 드롭다운 (월에 따라 동적 생성)"""
        self.draft = draft
        self.year = year
        self.month = month
        
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
        max_day = min(31, days_in_month)
        options = [discord.SelectOption(label=f"{day}일", value=str(day)) for day in range(16, max_day + 1)]
        
        super().__init__(
            placeholder="📅 16-31일 중 선택",
            min_values=1,
            max_values=1,
            options=options if options else [discord.SelectOption(label="없음", value="0", disabled=True)],
            custom_id="select_date_2",
        )
    
    async def callback(self, interaction: discord.Interaction):
        day = int(self.values[0])
        selected_date = now_kst().replace(year=self.year, month=self.month, day=day, hour=0, minute=0, second=0, microsecond=0)
        
        # defer 및 원본 메시지 삭제
        await interaction.response.defer(ephemeral=True)
        await interaction.delete_original_response()
        
        embed = discord.Embed(
            title="🕒 시간 선택",
            description=f"**{format_date_with_day(selected_date)}** 에서 시작 시간을 선택하세요.",
            color=discord.Color.blurple(),
        )
        
        time_view = discord.ui.View(timeout=300)
        time_view.add_item(TimeSelect(self.draft, selected_date))
        
        await interaction.followup.send(embed=embed, view=time_view, ephemeral=True)


class CalendarSelectView(discord.ui.View):
    """간단한 달력 UI (월 선택 → 날짜 선택 → 시간 선택)"""
    def __init__(self, draft: dict):
        super().__init__(timeout=300)  # 5분 후 만료
        self.draft = draft
        self.current_date = now_kst()
    
    async def show_calendar(self, interaction: discord.Interaction):
        """캘린더를 표시합니다"""
        await interaction.response.defer(ephemeral=True)
        await self.render_calendar(interaction)
    
    async def render_calendar(self, interaction: discord.Interaction):
        """캘린더 UI를 렌더링합니다"""
        year = self.current_date.year
        month = self.current_date.month
        month_name = f"{year}년 {month}월"
        
        embed = discord.Embed(
            title="📅 날짜 선택",
            description=f"**{month_name}**에서 날짜를 선택하세요.",
            color=discord.Color.blurple(),
        )
        
        view = discord.ui.View(timeout=300)
        
        # 날짜 선택 드롭다운
        view.add_item(DateSelect1(self.draft, year, month))
        view.add_item(DateSelect2(self.draft, year, month))
        
        # 이전/다음 달 버튼
        prev_btn = discord.ui.Button(label="◀️ 이전달", style=discord.ButtonStyle.secondary)
        async def prev_callback(inter):
            from datetime import timedelta
            self.current_date = self.current_date.replace(day=1)
            self.current_date = self.current_date - timedelta(days=1)
            await inter.response.defer(ephemeral=True)
            await self.render_calendar(inter)
        prev_btn.callback = prev_callback
        view.add_item(prev_btn)
        
        next_btn = discord.ui.Button(label="다음달 ▶️", style=discord.ButtonStyle.secondary)
        async def next_callback(inter):
            from datetime import timedelta
            last_day = 28  # 시작점
            while True:
                try:
                    self.current_date = self.current_date.replace(day=last_day + 1)
                    break
                except ValueError:
                    last_day += 1
                    if last_day > 31:
                        break
            if self.current_date.month == 12:
                self.current_date = self.current_date.replace(year=self.current_date.year + 1, month=1, day=1)
            else:
                self.current_date = self.current_date.replace(month=self.current_date.month + 1, day=1)
            await inter.response.defer(ephemeral=True)
            await self.render_calendar(inter)
        next_btn.callback = next_callback
        view.add_item(next_btn)
        
        try:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            print(f"Error in render_calendar: {e}")


async def create_lobby_from_draft(interaction: discord.Interaction, draft: dict, already_deferred: bool = False):
    """사용자 입력(draft)을 기반으로 로비 생성
    
    동작:
    1. 포럼 채널 사용 시: 스레드 생성 + 로비 메시지 전송
    2. 일반 채널 사용 시: 채널에 로비 메시지 전송
    3. DB에 로비 정보 저장
    4. 패널 업데이트
    """
    map_name = draft.get("map", "미설정")
    selected_date = draft.get("selected_date")
    start_time = draft.get("start_time", "00:00")
    channel_id_for_db = interaction.channel_id or 0
    
    if not selected_date or not start_time:
        await send_ephemeral_and_delete(interaction, "날짜와 시간을 다시 선택해주세요.")
        return
    
    # 이미 defer된 경우 스킵
    if not already_deferred:
        await interaction.response.defer(ephemeral=True)
    
    deleter = await send_ephemeral_get_deleter(interaction, "로비 생성 중...")
    
    # 선택된 날짜와 시간 조합
    hh, mm = map(int, start_time.split(":"))
    start_at_iso = iso_kst(selected_date.replace(hour=hh, minute=mm, second=0, microsecond=0))
    
    # 포럼 제목이 있으면 그것 사용, 없으면 자동 생성
    if draft.get("forum_title"):
        final_title = draft["forum_title"]
    else:
        final_title = format_forum_title(map_name, start_at_iso, "내전")
    
    draft["title"] = final_title
    
    # 포럼 채널로 포스트 생성
    forum_post_id = None
    lobby_message_id = None
    
    if FORUM_CHANNEL_ID:
        print(f"[DEBUG] FORUM_CHANNEL_ID: {FORUM_CHANNEL_ID}")
        try:
            forum_channel = client.get_channel(FORUM_CHANNEL_ID)
            if not forum_channel:
                forum_channel = await client.fetch_channel(FORUM_CHANNEL_ID)
            
            print(f"[DEBUG] forum_channel: {forum_channel}, type: {type(forum_channel).__name__}")
            
            if isinstance(forum_channel, discord.ForumChannel):
                print("[DEBUG] 포럼 채널 감지됨")
                try:
                    print(f"[DEBUG] 포럼 포스트 제목: {final_title}")
                    
                    try:
                        image_file = get_image_file()
                        print(f"[DEBUG] 이미지 파일 로드됨: {image_file.filename}")
                        thread, image_msg = await forum_channel.create_thread(
                            name=final_title,
                            file=image_file,
                        )
                        forum_post_id = thread.id
                        channel_id_for_db = thread.id
                        print(f"[DEBUG] 포럼 포스트 생성됨: {forum_post_id}")
                        
                        embed = lobby_embed_from_db({
                            'title': draft["title"],
                            'capacity': int(draft["capacity"]),
                            'map_name': map_name,
                            'start_at': start_at_iso,
                            'status': 'open',
                            'host_id': interaction.user.id,
                            'host_name': interaction.user.display_name or interaction.user.name or str(interaction.user.id),
                            'lobby_message_id': 0,
                        })
                        embed_msg = await thread.send(embed=embed, view=LobbyView.persistent())
                        lobby_message_id = embed_msg.id
                        print(f"[DEBUG] 포스트 임베드 메시지 전송됨: {embed_msg.id}")
                    except FileNotFoundError as fe:
                        print(f"Warning: 이미지 파일을 찾을 수 없습니다. {fe}")
                        await send_ephemeral_and_delete(interaction, f"이미지 파일을 찾을 수 없습니다: {IMAGE_PATH}", delay=10)
                        return
                    except Exception as fe:
                        print(f"Error creating forum post: {fe}")
                        import traceback
                        traceback.print_exc()
                        await send_ephemeral_and_delete(interaction, f"포럼 포스트 생성 중 오류: {fe}", delay=10)
                        return
                except Exception as e:
                    print(f"Error creating forum post: {e}")
                    import traceback
                    traceback.print_exc()
                    await send_ephemeral_and_delete(interaction, f"포럼 포스트 생성 중 오류: {e}", delay=10)
                    return
            else:
                print(f"[DEBUG] 포럼 채널이 아님. 채널 유형: {type(forum_channel).__name__}")
                await send_ephemeral_and_delete(interaction, f"포럼 채널이 아닙니다. 채널 유형: {type(forum_channel).__name__}", delay=8)
                return
        except Exception as e:
            print(f"Error fetching forum channel: {e}")
            import traceback
            traceback.print_exc()
            await send_ephemeral_and_delete(interaction, f"포럼 채널 조회 중 오류: {e}", delay=8)
            return
    else:
        print("[DEBUG] FORUM_CHANNEL_ID가 설정되지 않음, 채널 방식으로 전송")
        channel = interaction.channel
        if channel is None:
            await send_ephemeral_and_delete(interaction, "채널 정보를 확인할 수 없습니다.")
            return
        
        temp_embed = discord.Embed(title="로비 생성 중...", color=discord.Color.blurple())
        try:
            image_file = get_image_file()
            msg = await channel.send(embed=temp_embed, file=image_file, view=LobbyView.persistent())
        except FileNotFoundError as fe:
            print(f"Warning: 이미지 파일을 찾을 수 없습니다. {fe}")
            msg = await channel.send(embed=temp_embed, view=LobbyView.persistent())
        lobby_message_id = msg.id
        channel_id_for_db = channel.id

    db_create_lobby(
        lobby_message_id=lobby_message_id,
        guild_id=interaction.guild_id or 0,
        channel_id=channel_id_for_db,
        host_id=interaction.user.id,
        host_name=interaction.user.display_name or interaction.user.name or str(interaction.user.id),
        title=draft["title"],
        capacity=int(draft["capacity"]),
        map_name=map_name,
        start_at_iso=start_at_iso,
        forum_post_id=forum_post_id,
        status="open",
    )

    lobby = db_get_lobby(lobby_message_id)
    
    if FORUM_CHANNEL_ID and forum_post_id:
        forum_channel = client.get_channel(FORUM_CHANNEL_ID)
        if isinstance(forum_channel, discord.ForumChannel):
            try:
                thread = forum_channel.get_thread(forum_post_id)
                if thread is None:
                    thread = await client.fetch_channel(forum_post_id)

                if not isinstance(thread, discord.Thread):
                    raise TypeError(f"forum_post_id={forum_post_id} is not a Thread (got {type(thread)})")
                
                msg = await thread.fetch_message(lobby_message_id)
                embed = lobby_embed_from_db(lobby)
                await msg.edit(embed=embed, view=LobbyView.persistent())
                print("[DEBUG] 포럼 포스트에 로비 임베드 업데이트됨")
            except Exception as e:
                print(f"Error updating lobby embed in forum post: {e}")
    else:
        if interaction.channel:
            try:
                msg = await interaction.channel.fetch_message(lobby_message_id)
                embed = lobby_embed_from_db(lobby)
                await msg.edit(embed=embed, view=LobbyView.persistent())
            except Exception as e:
                print(f"Error updating lobby message: {e}")

    try:
        await update_lobby_panel()
    except Exception:
        pass
    
    try:
        await interaction.delete_original_response()
    except Exception:
        pass
    try:
        await deleter()
    except Exception:
        pass


class TimeSelectSimple(discord.ui.Select):
    """시간 선택 드롭다운 (미사용: CalendarSelectView의 TimeSelect로 대체됨)"""
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
    """미사용 클래스 (레거시)
    
    이전에는 로비 생성 최종 확인에 사용했으나,
    현재는 TimeSelect에서 직접 처리
    """
    def __init__(self, draft: dict):
        super().__init__(timeout=180)
        self.draft = draft

    async def render(self, interaction: discord.Interaction):
        """미사용"""
        pass

    @discord.ui.button(label="생성", style=discord.ButtonStyle.success, custom_id="finalize:create")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        """미사용"""
        pass


# ▼ 로비 메시지 버튼 (참가/취소/마감/시작/내전취소)
# persistent=True: 봇 재시작 후에도 버튼 반응 유지
class LobbyView(discord.ui.View):
    """로비 메시지의 버튼 모음 (참가/취소/마감/시작/내전취소)
    
    persistent=True: 봇 재시작 후에도 버튼이 반응함
    """
    def __init__(self):
        super().__init__(timeout=None)  # 타임아웃 없음 (persistent)

    @staticmethod
    def persistent() -> "LobbyView":
        """persistent view 생성 헬퍼"""
        return LobbyView()

    def get_lobby(self, interaction: discord.Interaction) -> sqlite3.Row | None:
        """메시지 ID로 로비 정보 조회"""
        if interaction.message is None:
            return None
        return db_get_lobby(interaction.message.id)

    def is_host(self, interaction: discord.Interaction, lobby: sqlite3.Row) -> bool:
        """현재 사용자가 로비 호스트인지 확인"""
        return interaction.user.id == int(lobby["host_id"])

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="lobby:join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """로비 참가 버튼
        
        협곡: 포지션/티어 선택 UI 표시
        칼바람: 즉시 참가
        """
        lobby = self.get_lobby(interaction)
        if not lobby:
            await send_ephemeral_and_delete(interaction, "로비 정보를 찾을 수 없습니다.")
            return
        if lobby["status"] != "open":
            await send_ephemeral_and_delete(interaction, "이미 마감/시작된 로비입니다.")
            return

        lobby_id = int(lobby["lobby_message_id"])
        uid = interaction.user.id

        # 협곡이 아닌 경우: 포지션/티어 저장하지 않음(NULL)
        if lobby["map_name"] != "소환사의 협곡":
            await interaction.response.defer(ephemeral=True)
            deleter = await send_ephemeral_get_deleter(interaction, "참가 처리 중...")

            try:
                add_status, member_count = db_try_add_member(
                    lobby_id,
                    uid,
                    None,
                    None,
                    None,
                    int(lobby["capacity"]),
                )
                if add_status == "already":
                    await send_ephemeral_and_delete(interaction, "이미 참가하셨습니다.")
                    return
                if add_status == "full":
                    await send_ephemeral_and_delete(interaction, "정원이 가득 찼습니다.")
                    return
                # 마감 체크
                if member_count >= int(lobby["capacity"]):
                    db_update_lobby_status(lobby_id, "closed")

                # 메시지 갱신
                try:
                    await interaction.message.edit(embed=lobby_embed_from_db(db_get_lobby(lobby_id)), view=LobbyView.persistent())
                except Exception as e:
                    print(f"Error editing lobby message: {e}")
            finally:
                try:
                    await deleter()
                except Exception:
                    pass

            try:
                await update_lobby_panel()
            except Exception:
                pass

            return

        # 협곡인 경우: 선택 UI
        view = JoinSelectionView(lobby_id)
        await interaction.response.send_message("티어와 포지션을 선택한 뒤 '참가'를 누르세요.", view=view, ephemeral=True)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, custom_id="lobby:leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """로비 참가 취소 버튼"""
        lobby = self.get_lobby(interaction)
        if not lobby:
            await send_ephemeral_and_delete(interaction, "로비 정보를 찾을 수 없습니다.")
            return
        if lobby["status"] != "open":
            await send_ephemeral_and_delete(interaction, "마감/시작된 로비는 취소할 수 없습니다.")
            return

        lobby_id = int(lobby["lobby_message_id"])
        uid = interaction.user.id

        if not db_is_member(lobby_id, uid):
            await send_ephemeral_and_delete(interaction, "참가 상태가 아닙니다.")
            return

        await interaction.response.defer(ephemeral=True)
        db_remove_member(lobby_id, uid)

        # 로비 메시지 갱신 (취소한 멤버 제거)
        try:
            # 남은 모든 멤버의 멘션을 포함
            current_members = db_list_members(lobby_id)
            member_mentions = " ".join([f"<@{int(m['user_id'])}>" for m in current_members])
            await interaction.message.edit(
                content=member_mentions if member_mentions else None,
                embed=lobby_embed_from_db(db_get_lobby(lobby_id)),
                view=LobbyView.persistent()
            )
        except Exception as e:
            print(f"Error updating lobby message on leave: {e}")
        try:
            await update_lobby_panel()
        except Exception:
            pass

    @discord.ui.button(label="마감", style=discord.ButtonStyle.danger, custom_id="lobby:close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """정원 마감 버튼 (호스트만 사용 가능)"""
        lobby = self.get_lobby(interaction)
        if not lobby:
            await send_ephemeral_and_delete(interaction, "로비 정보를 찾을 수 없습니다.")
            return
        if not self.is_host(interaction, lobby):
            await send_ephemeral_and_delete(interaction, "호스트만 마감할 수 있습니다.")
            return
        if lobby["status"] != "open":
            await send_ephemeral_and_delete(interaction, "이미 마감/시작된 로비입니다.")
            return

        lobby_id = int(lobby["lobby_message_id"])

        await interaction.response.defer(ephemeral=True)
        db_update_lobby_status(lobby_id, "closed")
        # 현재 멘션 유지
        try:
            current_members = db_list_members(lobby_id)
            member_mentions = " ".join([f"<@{int(m['user_id'])}>" for m in current_members])
            await interaction.message.edit(
                content=member_mentions if member_mentions else None,
                embed=lobby_embed_from_db(db_get_lobby(lobby_id)), 
                view=LobbyView.persistent()
            )
        except Exception as e:
            print(f"Error updating lobby on close: {e}")
        try:
            await update_lobby_panel()
        except Exception:
            pass
        
        # 마감 알림 메시지
        try:
            current_members = db_list_members(lobby_id)
            if current_members:
                member_mentions = " ".join([f"<@{int(m['user_id'])}>" for m in current_members])
                close_msg = f"{member_mentions}\n\n🟥 **인원 모집이 마감되었습니다.**"
                await interaction.channel.send(close_msg)
        except Exception as e:
            print(f"[ERROR] 마감 알림 메시지 전송 실패: {e}")

    @discord.ui.button(label="시작", style=discord.ButtonStyle.primary, custom_id="lobby:start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """게임 시작 버튼 (호스트만 사용 가능)"""
        lobby = self.get_lobby(interaction)
        if not lobby:
            await send_ephemeral_and_delete(interaction, "로비 정보를 찾을 수 없습니다.")
            return
        if not self.is_host(interaction, lobby):
            await send_ephemeral_and_delete(interaction, "호스트만 시작할 수 있습니다.")
            return
        if lobby["status"] == "started":
            await send_ephemeral_and_delete(interaction, "이미 시작된 로비입니다.")
            return

        lobby_id = int(lobby["lobby_message_id"])

        await interaction.response.defer(ephemeral=True)
        db_update_lobby_status(lobby_id, "started")
        # 현재 멘션 유지
        try:
            current_members = db_list_members(lobby_id)
            member_mentions = " ".join([f"<@{int(m['user_id'])}>" for m in current_members])
            await interaction.message.edit(
                content=member_mentions if member_mentions else None,
                embed=lobby_embed_from_db(db_get_lobby(lobby_id)), 
                view=LobbyView.persistent()
            )
        except Exception as e:
            print(f"Error updating lobby on start: {e}")
        try:
            await update_lobby_panel()
        except Exception:
            pass

    @discord.ui.button(label="내전 취소", style=discord.ButtonStyle.danger, custom_id="lobby:cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """내전 완전 취소 버튼 (호스트만 사용 가능)
        
        동작: 로비 메시지에서 모든 버튼 제거, 참가자에게 멘션 알림
        """
        lobby = self.get_lobby(interaction)
        if not lobby:
            await send_ephemeral_and_delete(interaction, "로비 정보를 찾을 수 없습니다.")
            return
        if not self.is_host(interaction, lobby):
            await send_ephemeral_and_delete(interaction, "호스트만 취소할 수 있습니다.")
            return

        lobby_id = int(lobby["lobby_message_id"])

        await interaction.response.defer(ephemeral=True)
        
        # 참가자 목록 조회
        members = db_list_members(lobby_id)
        member_ids = [int(m["user_id"]) for m in members]
        
        # 로비 상태 업데이트
        db_update_lobby_status(lobby_id, "cancelled")

        # 메시지 버튼 제거 및 content 초기화
        try:
            await interaction.message.edit(
                content=None,
                embed=lobby_embed_from_db(db_get_lobby(lobby_id)), 
                view=None
            )
        except Exception as e:
            print(f"Error updating lobby on cancel: {e}")
        try:
            await update_lobby_panel()
        except Exception:
            pass
        
        # 참가자들에게 멘션 알림
        if member_ids:
            mention_str = " ".join([f"<@{uid}>" for uid in member_ids])
            cancel_msg = f"{mention_str}\n\n🚨 **내전이 취소되었습니다.**\n\n로비명: `{lobby['title']}`"
            
            try:
                # 같은 채널에 취소 알림 메시지 전송
                await interaction.channel.send(cancel_msg)
            except Exception as e:
                print(f"[ERROR] 취소 알림 메시지 전송 실패: {e}")


# ▼ 채널에 설치되는 "로비 생성" 버튼 (persistent=True)
class CreateLobbyView(discord.ui.View):
    """패널에 표시되는 "로비 생성" 버튼"""
    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="🎮 내전 로비 생성", style=discord.ButtonStyle.blurple, custom_id="create_lobby_btn")
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """로비 생성 버튼 → CreateLobbyModal 표시"""
        await interaction.response.send_modal(CreateLobbyModal())


# ▼ 미사용 (슬래시 명령으로 구현됨)
class AdminLobbyResetView(discord.ui.View):
    """초기화 버튼 (현재 슬래시 명령 /내전_초기화로 대체됨)"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🧹 내전 목록 초기화", style=discord.ButtonStyle.danger, custom_id="reset_lobbies_btn")
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        perms = interaction.user.guild_permissions
        if not (perms.administrator or perms.manage_guild):
            await send_ephemeral_and_delete(interaction, "이 작업을 수행할 권한이 없습니다.")
            return

        await interaction.response.defer(ephemeral=True)
        await reset_all_lobbies()
        await send_ephemeral_and_delete(interaction, "모든 내전 목록을 초기화했습니다.")


# ================================
# 로비 패널 (모집 중 로비 목록 표시)
# ================================
def is_lobby_panel_message(msg: discord.Message) -> bool:
    """메시지가 로비 패널인지 확인
    
    판별 기준:
    - 봇이 작성한 메시지
    - 제목이 "🎮 롤 내전 로비"
    - "로비 생성" 버튼 포함
    """
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

def build_lobby_panel_embed() -> discord.Embed:
    """모집 중인 로비 목록을 표시하는 임베드 생성
    
    내용: 각 로비의 제목, 맵, 시간, 인원/정원
    제약: 필드당 1024자 제한이므로 길면 여러 필드로 분할
    """
    """모집 중인 로비 목록을 표시하는 패널 임베드
    
    내용: 각 로비의 맵, 시간, 인원/정원
    갱신: 로비 생성/참가/취소 후 호출
    """
    embed = discord.Embed(
        title="🎮 롤 내전 로비",
        description="아래 버튼을 클릭하여 로비를 생성하세요!",
        color=discord.Color.blurple(),
    )

    open_lobbies = db_list_open_lobbies()
    if not open_lobbies:
        embed.add_field(name="현재 모집 중인 내전", value="*(없음)*", inline=False)
    else:
        # 각 로비를 "제목\n맵·시간·인원" 2줄 포맷으로 표시
        lines: list[str] = []
        for lobby in open_lobbies:
            lobby_id = int(lobby["lobby_message_id"])
            member_count = db_count_members(lobby_id)
            cap = int(lobby["capacity"])
            map_name = lobby["map_name"]
            start_at = format_start_at(lobby["start_at"])
            title = lobby["title"]
            lines.append(
                "\n".join([
                    f"• **{title}**",
                    f"  🗺 {map_name} · 🕒 {start_at} · 👥 {member_count}/{cap}",
                ])
            )

        # Discord 필드 1024자 제한 때문에 긴 목록을 여러 필드로 분할
        chunks: list[str] = []
        current = ""
        for line in lines:
            next_value = f"{current}\n{line}" if current else line
            if len(next_value) > 1024:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = next_value
        if current:
            chunks.append(current)

        for idx, chunk in enumerate(chunks):
            name = "현재 모집 중인 내전" if idx == 0 else "현재 모집 중인 내전 (계속)"
            embed.add_field(name=name, value=chunk, inline=False)

    return embed


async def fetch_lobby_message(lobby: sqlite3.Row) -> discord.Message | None:
    """DB에 저장된 로비 메시지 조회
    
    포럼 스레드 또는 일반 채널에서 메시지 검색:
    1. 포럼 스레드 확인 (forum_post_id 있으면)
    2. 일반 채널 확인 (channel_id)
    
    Returns:
        Discord 메시지 객체 | 찾을 수 없으면 None
    """
    lobby_id = int(lobby["lobby_message_id"])
    channel_id = int(lobby["channel_id"])
    forum_post_id = lobby["forum_post_id"]

    if forum_post_id and FORUM_CHANNEL_ID:
        forum_channel = client.get_channel(FORUM_CHANNEL_ID)
        if forum_channel is None:
            try:
                forum_channel = await client.fetch_channel(FORUM_CHANNEL_ID)
            except Exception:
                forum_channel = None

        if isinstance(forum_channel, discord.ForumChannel):
            try:
                thread = forum_channel.get_thread(int(forum_post_id))
                if thread is None:
                    thread = await client.fetch_channel(int(forum_post_id))
                if isinstance(thread, discord.Thread):
                    return await thread.fetch_message(lobby_id)
            except Exception:
                return None

    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except Exception:
            channel = None

    if channel is None:
        return None

    try:
        return await channel.fetch_message(lobby_id)
    except Exception:
        return None


async def install_panel_if_missing():
    """로비 패널이 없으면 생성
    
    로직: 첫 번째 서버의 채널 중 로비 패널 메시지 검색
    없으면: 봇이 메시지 전송 가능한 첫 채널에 생성
    """
    # 서버 1개 기준: 첫 guild에만 설치
    for guild in client.guilds:
        installed = False
        target_channel = None

        # LOBBY_PANEL_CHANNEL_ID가 지정되면 그 채널을 사용
        if LOBBY_PANEL_CHANNEL_ID:
            target_channel = client.get_channel(LOBBY_PANEL_CHANNEL_ID)
            if not target_channel:
                try:
                    target_channel = await client.fetch_channel(LOBBY_PANEL_CHANNEL_ID)
                except Exception as e:
                    print(f"[WARNING] LOBBY_PANEL_CHANNEL_ID {LOBBY_PANEL_CHANNEL_ID}를 찾을 수 없습니다: {e}")
                    target_channel = None
        
        # 특정 채널 또는 첫 번째 사용 가능 채널 확인
        if target_channel:
            channels_to_check = [target_channel]
        else:
            channels_to_check = guild.text_channels
        
        # 이미 설치되어 있는지 확인
        for channel in channels_to_check:
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

        # 설치되지 않았으면 생성
        if not installed:
            for channel in channels_to_check:
                if channel.permissions_for(guild.me).send_messages:
                    embed = build_lobby_panel_embed()
                    await channel.send(embed=embed, view=CreateLobbyView())
                    installed = True
                    break

        break


async def update_lobby_panel():
    """기존 로비 패널 메시지 업데이트
    
    호출 시점: 로비 생성/참가/취소 등 상태 변화 시
    동작: 현재 모집 중인 로비 목록으로 임베드 갱신
    """
    for guild in client.guilds:
        target_channel = None

        if LOBBY_PANEL_CHANNEL_ID:
            target_channel = client.get_channel(LOBBY_PANEL_CHANNEL_ID)
            if not target_channel:
                try:
                    target_channel = await client.fetch_channel(LOBBY_PANEL_CHANNEL_ID)
                except Exception as e:
                    print(f"[WARNING] LOBBY_PANEL_CHANNEL_ID {LOBBY_PANEL_CHANNEL_ID}를 찾을 수 없습니다: {e}")
                    target_channel = None

        if target_channel:
            channels_to_check = [target_channel]
        else:
            channels_to_check = guild.text_channels

        panel_msg = None
        for channel in channels_to_check:
            if not channel.permissions_for(guild.me).send_messages:
                continue
            try:
                async for msg in channel.history(limit=50):
                    if is_lobby_panel_message(msg):
                        panel_msg = msg
                        break
            except Exception:
                continue
            if panel_msg:
                break

        if panel_msg:
            try:
                embed = build_lobby_panel_embed()
                await panel_msg.edit(embed=embed, view=CreateLobbyView())
            except Exception as e:
                print(f"[ERROR] 로비 패널 업데이트 실패: {e}")

        break


async def reset_all_lobbies():
    """모든 로비 초기화 (관리자 슬래시 명령)
    
    동작:
    1. 모든 참가 정보 삭제
    2. 모든 로비 상태를 "cancelled"로 변경
    3. 각 로비 메시지에서 버튼 제거 (병렬 처리로 빠르게)
    4. 패널 갱신
    """
    lobbies = db_list_all_lobbies()
    if not lobbies:
        await update_lobby_panel()
        return

    db_clear_all_members()  # 모든 참가자 정보 삭제

    # 모든 로비의 status를 먼저 업데이트
    for lobby in lobbies:
        lobby_id = int(lobby["lobby_message_id"])
        db_update_lobby_status(lobby_id, "cancelled")

    # 메시지 업데이트를 동시에 처리 (병렬 처리로 성능 향상)
    async def update_single_lobby(lobby: sqlite3.Row):
        try:
            msg = await fetch_lobby_message(lobby)
            if msg:
                embed = lobby_embed_from_db(lobby)
                await msg.edit(embed=embed, view=None, content=None)  # 버튼 제거
        except Exception:
            pass

    # asyncio.gather로 모든 메시지 업데이트를 병렬 처리
    await asyncio.gather(*[update_single_lobby(lobby) for lobby in lobbies], return_exceptions=True)

    await update_lobby_panel()


async def trigger_admin_reset(interaction: discord.Interaction):
    """관리자 권한 확인 후 초기화 (미사용: 슬래시 명령으로 대체)"""
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild):
        await send_ephemeral_and_delete(interaction, "이 작업을 수행할 권한이 없습니다.")
        return

    await interaction.response.defer(ephemeral=True)
    await reset_all_lobbies()
    await send_ephemeral_and_delete(interaction, "모든 내전 목록을 초기화했습니다.")

async def restore_lobbies_on_start():
    """봇 시작 시 기존 로비 복구
    
    동작:
    1. DB에서 활성 로비(open/closed/started) 조회
    2. 각 로비 메시지에 버튼 재부착 (persistent view)
    3. 취소된 로비: 버튼 제거
    
    목적: 봇 재시작 후에도 로비 버튼이 반응하도록 유지
    """
    # 재시작 시 DB 기반으로 로비 메시지에 View 재부착 + 임베드 최신화
    for lobby in db_list_active_lobbies():
        lobby_id = int(lobby["lobby_message_id"])
        msg = await fetch_lobby_message(lobby)
        if msg is None:
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


# ================================
# 봇 이벤트핸들러
# ================================
@client.event
async def on_ready():
    """봇 시작 시 한 번만 실행되는 초기화 함수
    
    순서:
    1. 데이터베이스 테이블 생성
    2. Persistent view(버튼) 등록 → 재시작 후 반응 유지
    3. 슬래시 명령어 동기화
    4. 패널 메시지 생성 (미존재 시)
    5. 기존 로비 메시지에 버튼 재부착
    6. 패널 업데이트
    """
    print("[DEBUG] on_ready 시작")
    try:
        init_db()
        print("[DEBUG] 데이터베이스 초기화 완료")
    except Exception as e:
        print(f"[ERROR] 데이터베이스 초기화 실패: {e}")
        return

    # persistent view 등록: 봇 재시작 후에도 버튼이 반응하도록
    try:
        client.add_view(CreateLobbyView())
        print("[DEBUG] CreateLobbyView 등록 완료")
        client.add_view(LobbyView.persistent())
        print("[DEBUG] LobbyView 등록 완료")
    except Exception as e:
        print(f"[ERROR] View 등록 실패: {e}")
        return

    # 슬래시 명령어(/내전_초기화) 등록/갱신
    try:
        await tree.sync()
        print("[INFO] 슬래시 명령 동기화 완료")
    except Exception as e:
        print(f"[ERROR] 슬래시 명령 동기화 실패: {e}")

    try:
        await install_panel_if_missing()
        print("[DEBUG] 패널 설치 완료")
    except Exception as e:
        print(f"[ERROR] 패널 설치 실패: {e}")

    try:
        await restore_lobbies_on_start()
        print("[DEBUG] 로비 복원 완료")
    except Exception as e:
        print(f"[ERROR] 로비 복원 실패: {e}")

    print("[INFO] 봇 준비 완료")

    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print(f"DB_PATH = {DB_PATH.resolve()}")
    print(f"FORUM_CHANNEL_ID = {FORUM_CHANNEL_ID}")
    print(f"LOBBY_PANEL_CHANNEL_ID = {LOBBY_PANEL_CHANNEL_ID}")
    print(f"IMAGE_PATH = {IMAGE_PATH}")

    await install_panel_if_missing()
    await restore_lobbies_on_start()
    await update_lobby_panel()


# ================================
# 슬래시 명령어
# ================================
@tree.command(
    name="내전_초기화",
    description="모든 내전 목록을 초기화함 (관리자만 사용 가능)"
)
@discord.app_commands.default_permissions(administrator=True)  # 관리자만 사용 가능
async def reset_lobbies_command(interaction: discord.Interaction):
    """관리자 초기화 명령어
    
    동작: 모든 로비 상태를 취소로 변경, 버튼 제거, 참가 정보 삭제
    """
    await interaction.response.defer(ephemeral=True)
    await reset_all_lobbies()
    await interaction.followup.send("✅ 모든 내전 목록을 초기화함", ephemeral=True)

# ================================
# 봇 실행
# ================================
client.run(TOKEN)  # Discord에 연결하고 봇 시작
