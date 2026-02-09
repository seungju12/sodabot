import os
import discord, asyncio, datetime, pytz
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") # 토큰을 가져오기 위해 .env 로드

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print("소다봇 실행")
    await client.change_presence(status=discord.Status.online, activity=discord.Game("봇의 상태메세지"))

@client.event
async def on_message(message):
    if message.content == "테스트":
        await message.channel.send ("{} | {}, Hello".format(message.author, message.author.mention))        # 채널 메세지
        await message.author.send ("{} | {}, User, Hello".format(message.author, message.author.mention))   # DM
    
    if message.content == "특정입력":
        ch = client.get_channel(1469406207323275417) # 특정 채널에 메세지 출력
        await ch.send ("{} | {}, User, Hello 테스트".format(message.author, message.author.mention))

@client.event
async def on_message(message):
    if message.content == "임베드":
        embed = discord.Embed(title="제목", description="부제목", timestamp=datetime.datetime.now(pytz.timezone('UTC')), color=0x00ff00)

        embed.add_field(name="임베드 라인 1 - inline = false", value="라인 이름에 해당하는 값", inline=False) # \n 적용
        embed.add_field(name="임베드 라인 2 - inline = false", value="라인 이름에 해당하는 값", inline=False)

        embed.add_field(name="임베드 라인 3 - inline = true", value="라인 이름에 해당하는 값", inline=True) # \n 미적용
        embed.add_field(name="임베드 라인 4 - inline = true", value="라인 이름에 해당하는 값", inline=True)

        embed.set_footer(text="Bot Made by. Danpungsoda", icon_url="https://cdn.discordapp.com/attachments/667391118010351668/1469410352147202306/KakaoTalk_20260207_030015733.png?ex=69878e88&is=69863d08&hm=3f4181e34a81838c6b6f6a21f170708d9805de11de69e51b97489bf747a476d1&")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/667391118010351668/1469410352147202306/KakaoTalk_20260207_030015733.png?ex=69878e88&is=69863d08&hm=3f4181e34a81838c6b6f6a21f170708d9805de11de69e51b97489bf747a476d1&")
        await message.channel.send (embed=embed)

    if message.content.startswith ("/공지"):
        await message.channel.purge(limit=1)
        i = (message.author.guild_permissions.administrator)
        if i is True:
            notice = message.content[4:]
            channel = client.get_channel(1469406207323275417)
            embed = discord.Embed(title="**공지사항 제목 (볼드)*", description="\n――――――――――――――――――――――――――――\n\n{}\n\n――――――――――――――――――――――――――――".format(notice),timestamp=datetime.datetime.now(pytz.timezone('UTC')), color=0x00ff00)
            embed.set_footer(text="Bot Made by. Danpungsoda | 담당 관리자 : {}".format(message.author), icon_url="https://cdn.discordapp.com/attachments/667391118010351668/1469410352147202306/KakaoTalk_20260207_030015733.png?ex=69878e88&is=69863d08&hm=3f4181e34a81838c6b6f6a21f170708d9805de11de69e51b97489bf747a476d1&")
            embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/667391118010351668/1469410352147202306/KakaoTalk_20260207_030015733.png?ex=69878e88&is=69863d08&hm=3f4181e34a81838c6b6f6a21f170708d9805de11de69e51b97489bf747a476d1&")
            await channel.send ("@everyone", embed=embed)
            await message.author.send("*[ BOT 자동 알림 ]* | 정상적으로 공지가 채널에 작성이 완료되었습니다 : )\n\n[ 기본 작성 설정 채널 ] : {}\n[ 공지 발신자 ] : {}\n\n[ 내용 ]\n{}".format(channel, message.author, notice))
 
        if i is False:
            await message.channel.send("{}, 당신은 관리자가 아닙니다".format(message.author.mention))

    if message.content.startswith ("/청소"):
        i = (message.author.guild_permissions.administrator)

        if i is True:
            amount = message.content[4:]
            await message.channel.purge(limit=1)
            await message.channel.purge(limit=int(amount))
            
            embed = discord.Embed(title="메시지 삭제 알림", description="최근 디스코드 채팅 {}개가\n관리자 {}님의 요청으로 인해 정상 삭제 조치 되었습니다.".format(amount, message.author))
            embed.set_footer(text="Bot Made by. Danpungsoda", icon_url="https://cdn.discordapp.com/attachments/667391118010351668/1469410352147202306/KakaoTalk_20260207_030015733.png?ex=69878e88&is=69863d08&hm=3f4181e34a81838c6b6f6a21f170708d9805de11de69e51b97489bf747a476d1&")
            await message.channel.send(embed=embed)

        if i is False:
            await message.channel.send("{}, 당신은 명령어를 사용할 수 있는 권한이 없습니다.".format(message.author.mention))

    if message.content.startswith ("/인증"):
        i = (message.author.guild_permissions.administrator)
        if i is True:
            await message.channel.purge(limit=1)
            user = message.guild.get_member(int(message.content.split(' ')[1][3:21]))

            embed = discord.Embed(title="인증 시스템", description="인증이 정상적으로 완료 되었습니다!", timestamp=datetime.datetime.now(pytz.timezone('UTC')), color=0xff0000)
            embed.add_field(name="인증 대상자", value="{} ( {} )".format(user.name, user.mention), inline=False)
            embed.add_field(name="담당 관리자", value="{} ( {} )".format(message.author, message.author.mention), inline=False)
            embed.set_footer(text="Bot Made by, Danpungsoda", icon_url="https://cdn.discordapp.com/attachments/667391118010351668/1469410352147202306/KakaoTalk_20260207_030015733.png?ex=69878e88&is=69863d08&hm=3f4181e34a81838c6b6f6a21f170708d9805de11de69e51b97489bf747a476d1&")
            await message.channel.send (embed=embed)
            await user.add_roles(get(user.guild.roles, name="도우미"))

        if i is False:
            await message.channel.purge(limit=1)
            await message.channel.send(embed=discord.Embed(title="권한 부족", description = message.author.mention + "님은 유저를 인증할 수 있는 권한이 없습니다.", color = 0xff0000))
            return
        
client.run(TOKEN)