# History
## 2026-02-09
### on_ready() 로직 변경
채널 순회할 때 return 남발 제거

### LobbyView를 persistent view로 등록
재시작 후에도 버튼 동작하도록 변경

### 로비 식별 안정화
모든 로비 버튼 custom_id를 lobby:join:<message_id> 형태로 변경

### ephemeral 단순화
interaction.response.edit_message() 형태로 변경

### 로비 생성 패널 메세지 정확히 식별
embed title + create 버튼을 custom_id로 확인