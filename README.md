# Crewdock

> 한 대의 컴퓨터에서, 여러 사람에게 줄 **AI 비서를 각자 격리된 박스로** 띄우고
> 명령어 하나(`crew`)로 관리합니다.

## 한눈에

이것만 읽어도 전체가 잡힙니다.

- **상황** — AI 비서(에이전트) 하나를 여러 명에게 주려면, 보통 한 서버에 다 욱여넣게 된다
- **그러면** 서로의 기억·API 키·파일이 섞이고 → 한 명에서 난 문제가 전체로 번진다
- **그래서** Crewdock은 사람마다 **격리된 박스(컨테이너) 1개씩** 띄운다 — 기억·키·신원이 따로
- **근데** 박스를 일일이 손으로 만들면 번거로우니 → `crew` 명령 하나로 생성·운영·제거한다
- **그러면** `crew create alice` 한 줄로 새 비서가 뜨고, `crew rm alice`로 정리된다
- **게다가** 공통 지식(문서·브랜드 톤 등)은 **읽기 전용 레이어**로 깔아줄 수 있다 (비서는 읽되 못 고침)
- **실제로** 사용자는 텔레그램 봇으로 바로 대화하고, 운영은 웹 대시보드로 한다
- **단,** 대시보드는 보안상 이 컴퓨터(루프백) 전용 — 원격은 SSH 터널. 최종 사용자는 대시보드를 안 보고 메신저로만 쓴다

```bash
uv sync
crew create alice --type hermes --bot-token <봇토큰> --layer knowledge --credential anthropic
crew list
```

**↓ 궁금한 것만 골라 보세요.**

---

## 별첨 1 — 이게 뭔가요? (용어부터 쉽게)

- **에이전트(agent)** — 텔레그램 같은 메신저에서 말을 거는, 상주하는 AI 비서.
- **인스턴스(instance)** — 비서 한 "명". 실제로는 격리된 Docker 컨테이너 1개 + 자기 데이터 폴더.
- **격리(isolation)** — 인스턴스마다 기억·세션·API 키·신원(봇)이 **완전히 분리**됩니다. A의 대화나
  파일을 B가 볼 수 없고, A가 키를 많이 써도 B에 영향이 없습니다.
- **누구에게 좋나** — 가족·팀·고객에게 "각자 자기 비서"를 주고 싶은데, 한 머신에서 깔끔하게
  나눠 운영하고 싶은 경우.

> 범위: Crewdock은 "채팅으로 말 거는 상주 AI 비서"(예: Hermes, OpenClaw)를 호스팅합니다.
> 임의의 웹앱·DB 같은 일반 컨테이너 호스팅 도구는 아닙니다.

## 별첨 2 — 어떻게 시작하나요? (설치 + 첫 비서)

```bash
# 1) 의존성 설치 (uv 사용)
uv sync

# 2) 첫 인스턴스 생성 — 봇 토큰을 넣으면 컨테이너가 뜨고 포트가 자동 배정됩니다
crew create alice --type hermes --bot-token <텔레그램_봇_토큰>

# 3) 확인
crew list
crew status alice        # 대시보드 URL 표시 (예: http://127.0.0.1:9120/)
```

- 봇 토큰은 텔레그램 **@BotFather** 에서 발급받습니다.
- 모든 명령은 `uv run crew <명령>` 으로도 실행할 수 있습니다.
- 두 번째 인스턴스는 다음 빈 포트를 자동으로 받습니다(겹치지 않음).

## 별첨 3 — 어떤 명령들이 있나요?

| 명령어          | 설명                                                          |
| --------------- | ------------------------------------------------------------- |
| `crew create`   | 새 인스턴스 생성 (옵션 상세 → 별첨 3a)                        |
| `crew list`     | 전체 인스턴스 목록                                            |
| `crew status`   | 한 인스턴스의 상태·포트·대시보드 URL (롤백 가능한 이전 이미지 표시) |
| `crew logs`     | 컨테이너 로그 (`--follow` 로 실시간)                          |
| `crew start` / `stop` / `restart` | 인스턴스 시작·정지·재시작                   |
| `crew update`   | 설정 변경 반영 + 이미지 핀 관리 (옵션 상세 → 별첨 3b)         |
| `crew shell`    | 컨테이너 내부 셸 접속 (모델 인증도 여기서)                    |
| `crew layers`   | 사용 가능한 읽기 전용 데이터 레이어 목록                       |
| `crew credentials` | 자격증명 번들 목록 (키 이름만, 값은 표시 안 함)             |
| `crew expose`   | 인스턴스를 게이트웨이에 게시 (별첨 6a 참조)                   |
| `crew unexpose` | 인스턴스를 게이트웨이에서 제거                                |
| `crew gateway up` | 게이트웨이 시작 (별첨 6a 참조)                              |
| `crew gateway down` | 게이트웨이 중지                                           |
| `crew rm`       | 인스턴스 제거 (`--purge` 없으면 **데이터 보존**)              |

> 💡 **모델·provider 인증(로그인)은 crewdock이 아니라 Hermes가 담당합니다.** 실행 중인 인스턴스에 `crew shell <name>` 로 들어가 `hermes login` / `hermes auth add <provider>` / `hermes model` 을 실행하세요. (별도 `crew setup` 명령은 없습니다 — 실행 중 인스턴스와 포트가 충돌하던 문제로 제거했습니다.)

### 별첨 3a — `crew create` 옵션

```bash
crew create <name> [--type <type>] [--bot-token <token>]
                   [--layer <layer>] ...
                   [--credential <bundle>] ...
```

| 옵션 | 설명 |
|------|------|
| `--type` | 에이전트 타입 (기본값: `hermes`). `agents/<type>.yaml` 매니페스트에서 정의. |
| `--bot-token` | 텔레그램 봇 토큰 (`TELEGRAM_BOT_TOKEN`). |
| `--layer` | 마운트할 읽기 전용 데이터 레이어 (반복 가능). `crew layers` 로 목록 확인. |
| `--credential` | 주입할 자격증명 번들 이름 (반복 가능). `crew credentials` 로 목록 확인. |

### 별첨 3b — `crew update` 옵션

```bash
crew update <name>              # 설정 재렌더 + 현재 버전 pull/재시작 (핀 변경 없음)
crew update <name> --image <ref>     # 이미지 핀 변경 (태그 또는 @sha256:...)
crew update <name> --rollback        # 이전 이미지로 복원
crew update <name> --to-default      # 매니페스트 기본 이미지로 복원
crew update --all [--backup]         # 전체 인스턴스 업데이트
```

- **bare update** (플래그 없음) — 설정(`_shared.env`, `credentials`)을 재렌더하고 현재 핀 이미지를 pull + 재시작합니다. 버전은 바뀌지 않습니다.
- `--image <ref>` / `--rollback` / `--to-default` 는 서로 **배타적**이며, 이미지 핀을 변경합니다. 변경 실패(pull 오류 등) 시 meta와 compose가 원래대로 복원됩니다.
- `--backup` — 재시작 전에 `data/`를 `data.bak-<timestamp>/`로 스냅샷합니다.
- `--all` — 이름 대신 전체 인스턴스를 순서대로 업데이트합니다.

## 별첨 4 — 진짜로 격리되나요? (자격증명 + 데이터)

자격증명은 **2단계**로 병합됩니다(개별이 공용을 덮어씀).

- **`instances/_shared.env`** — 모든 인스턴스 공용(예: 공용 LLM 키). gitignore 처리 → 커밋 안 됨.
- **`instances/<name>/instance.env`** — 인스턴스별 비밀값(예: 각자의 `TELEGRAM_BOT_TOKEN`).

공용 값을 바꾸면 다음으로 실행 중인 인스턴스에 전파합니다(각 compose 재렌더 + 재적용):

```bash
crew update --all
```

데이터는 인스턴스마다 별도 폴더(`instances/<name>/data/`)에 쌓이고, **제거 시 기본 보존**됩니다
(아래 별첨 7).

## 별첨 5 — 공통 지식은 어떻게 깔아주나요? (데이터 레이어)

여러 비서가 공유할 자료(문서·가이드·브랜드 톤 등)를 **읽기 전용**으로 주입합니다.

```bash
crew layers                                   # 풀에 있는 레이어 목록
crew create alice --type hermes --layer knowledge   # 골라서 마운트 (반복 가능)
crew create bob   --type hermes                     # 아무것도 안 붙일 수도 있음(기본)
```

- 레이어는 `layers/<이름>/` 디렉토리(아무 파일이나)이고, 컨테이너 안에는
  `layers_mount` 아래에 **읽기 전용(`:ro`)** 으로 붙습니다 (예: `/opt/shared/knowledge`).
- 비서는 그 자료를 **읽을 수만 있고 수정할 수 없습니다.** 기본값은 "아무 레이어도 안 붙음".

## 별첨 5a — 자격증명 번들이란? (`crew credentials`)

공통 API 키(예: LLM 키)를 **번들**로 관리합니다. 번들은 `credentials/<이름>.env` 파일이고,
`crew create --credential <이름>` 으로 인스턴스에 주입됩니다.

```bash
crew credentials                   # 번들 목록 + 키 이름 (값은 표시 안 함)
```

출력 예:

```
anthropic             ANTHROPIC_API_KEY
openai                OPENAI_API_KEY
```

인스턴스에 주입되면 compose 환경변수로 전달됩니다 — 값은 compose 파일에 기록되지 않고
`credentials/<이름>.env` 에서 런타임에 읽힙니다.

## 별첨 6 — 대시보드는 어떻게 보나요?

각 인스턴스는 관리용 웹 대시보드(설정·API 키·세션)를 **이 컴퓨터의 루프백 포트**에 띄웁니다.
`crew status <name>` 에 URL이 나옵니다(예: `http://127.0.0.1:9120/`).

- **왜 루프백 전용인가** — 대시보드는 API 키를 다루므로, 보안상 LAN/인터넷에 노출하지 않습니다.
  그래서 **이 컴퓨터에서만** 열립니다.
- **다른 컴퓨터에서 보려면** SSH 터널을 쓰세요(직접 노출 금지):
  ```bash
  ssh -L 9120:127.0.0.1:9120 you@this-machine   # 이후 원격에서 http://localhost:9120
  ```
- **최종 사용자는 대시보드를 쓰지 않습니다.** 비서를 받은 사람은 **텔레그램 등 메신저로** 대화합니다.
  대시보드는 운영자(당신) 전용입니다.

> 봇이 응답하게 하려면 인스턴스 설정에서 `TELEGRAM_ALLOWED_USERS`에 사용자 ID를 넣으세요
> (또는 `GATEWAY_ALLOW_ALL_USERS`로 개방). 기본은 미인가 사용자 거부입니다.

## 별첨 6a — 외부에 안전하게 공개하려면? (`crew expose` + `crew gateway`)

대시보드는 기본적으로 루프백 전용입니다. 외부(팀·고객 등)에 안전하게 열어 주려면
**게이트웨이**를 씁니다 — Tailscale VPN + Google OAuth SSO가 앞단에서 인증을 처리합니다.

> 📘 여러 사용자에게 각자 대시보드를 나눠주는 전체 절차(인프라 셋업 → 사용자 추가 →
> 운영 → 보안 모델 → 트러블슈팅)는 **[docs/multi-user.md](docs/multi-user.md)** 참고.

```bash
# 1) 게이트웨이 시작 (최초 한 번)
crew gateway up
#    → URL + Google OAuth 리디렉트 URI 출력
#       Google Cloud Console에서 리디렉트 URI를 한 번만 등록하면 됩니다.

# 2) 인스턴스에서 허용할 Google 계정 설정
#    instances/<name>/instance.env 에서 아래 줄을 uncomment + 이메일 입력:
#    CREW_ALLOWED_EMAILS=you@example.com,colleague@example.com

# 3) 인스턴스를 게이트웨이에 게시
crew expose alice
#    → alice의 대시보드가 게이트웨이 URL 하위 경로에 연결됩니다.

# 4) 게시 취소
crew unexpose alice

# 5) 게이트웨이 중지
crew gateway down
```

- **인증 흐름** — 사용자가 게이트웨이 URL에 접속 → Google 로그인 → 이메일이
  `CREW_ALLOWED_EMAILS`에 있으면 해당 인스턴스 대시보드로 프록시됩니다.
- `CREW_ALLOWED_EMAILS`가 설정되지 않은 인스턴스는 `crew expose`해도 외부 접근이 차단됩니다.
- 게이트웨이는 한 번만 띄우면 되고, 게시된 모든 인스턴스를 통합 관리합니다.

## 별첨 7 — 지우면 데이터는요? (안전장치)

`crew rm` 은 **기본적으로 데이터를 보존**합니다 — 실수로 기억·세션을 날리지 않게.

```bash
crew rm alice            # 컨테이너만 제거, instances/alice/data 는 그대로
crew rm alice --purge    # 데이터까지 완전 삭제 (확인 후)
```

## 별첨 8 — 새 에이전트 종류를 추가하려면? (확장성)

에이전트 종류는 **선언적 매니페스트** `agents/<type>.yaml` 하나로 정의됩니다 — 이미지, 포트,
필요한 자격증명, 데이터/레이어 마운트, 네트워킹 방식(`network_mode: bridge|host`) 등.
**코어 코드를 건드리지 않고** 새 매니페스트만 추가하면 새 런타임을 호스팅할 수 있습니다.

```bash
# 예: 나중에 다른 런타임을 추가
#   agents/openclaw.yaml 작성 후
crew create carol --type openclaw
```

기본 동봉 타입은 `hermes`(NousResearch Hermes Agent)입니다.

## 별첨 8a — 이미지 버전은 어떻게 관리하나요? (이미지 핀)

매니페스트(`agents/hermes.yaml`)에 **기본 이미지**가 정의되어 있습니다 — 태그 또는
`@sha256:` 다이제스트로 안정적인 버전을 고정할 수 있습니다. 새 인스턴스는 이 기본값을 상속합니다.

```bash
# 현재 핀 확인
crew status alice               # image=... 항목

# 특정 버전으로 핀 변경 (실패 시 자동 복원)
crew update alice --image nousresearch/hermes-agent@sha256:<digest>

# 이전 버전으로 롤백
crew update alice --rollback

# 매니페스트 기본값으로 되돌리기
crew update alice --to-default
```

- 각 인스턴스는 **독립적인 이미지 핀**을 가집니다 — `--image` 로 인스턴스별로 다른 버전을 운영할 수 있습니다.
- `--image` / `--rollback` / `--to-default` 는 서로 배타적(동시 사용 불가)입니다.
- 핀 변경 중 pull 또는 up 실패 시 meta.json과 docker-compose.yml이 **원자적으로 복원**되어 중간 상태가 남지 않습니다.
- `crew update --all` 은 현재 핀을 유지한 채 전체 인스턴스를 pull + 재시작합니다(버전 무변경).

## 별첨 9 — 한계와 주의 (정직하게)

- **단일 머신 · 단일 운영자 전제.** 인스턴스끼리는 격리되지만, `crew` CLI를 쓸 수 있는 사람의
  권한 분리(RBAC)는 없습니다. CLI 접근 권한 = 모든 인스턴스 조작 가능.
- **헬스체크는 "대시보드 생존성"까지만** 봅니다. `status`가 초록이어도 봇의 메신저 연결까지
  보장하진 않습니다(MVP 한계).
- **자원 한도(mem/cpus)는 CLI 플래그가 아니라 매니페스트** (`agents/<type>.yaml`) 에서 설정합니다.
- **업데이트는 in-place 재생성**입니다. 이미지가 데이터 포맷을 바꾸는 경우를 대비해
  `crew update --backup` 으로 `data/` 스냅샷을 남길 수 있습니다(마이그레이션은 사용자 책임).

---

> **핵심 한 줄:** "사람마다 격리된 비서 한 명, 명령어 한 줄."

## 라이선스

MIT
