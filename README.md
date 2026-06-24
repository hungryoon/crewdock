# Crewdock

> 한 대의 머신에서 여러 사람에게 **각자 격리된 AI 비서**를 띄우고,
> **단일 로그인 게이트웨이**로 운영하는 CLI.

## Crewdock이란

채팅으로 말 거는 상주 AI 비서(에이전트, 예: [Hermes](https://github.com/NousResearch/hermes-agent))를 사람마다 **격리된 컨테이너 1개씩** 띄워 주는 도구입니다. 가족·팀·고객에게 "각자 자기 비서"를 주되, 한 머신에서 깔끔하게 나눠 운영하고 싶을 때 씁니다.

- **격리** — 인스턴스마다 기억·세션·API 키·신원이 완전히 분리됩니다. A의 대화·파일을 B가 볼 수 없고, A가 키를 많이 써도 B에 영향이 없습니다.
- **한 줄 운영** — `crew create alice` 로 새 비서가 뜨고, `crew rm alice` 로 정리됩니다.
- **단일 로그인** — Tailscale + Google SSO 게이트웨이 하나로, 여러 사람이 각자 대시보드를 받습니다.

```
                      ┌─ 단일 로그인 게이트웨이 ─┐
   사용자 ── 구글 SSO ─┤  Tailscale + oauth2-proxy │
                      └────────────┬─────────────┘
              ┌────────────────────┼────────────────────┐
        ┌─────┴─────┐        ┌─────┴─────┐        ┌─────┴─────┐
        │  alice    │        │   bob     │        │  carol    │   ← 격리된 인스턴스
        │ data/키/  │        │ data/키/  │        │ data/키/  │     (컨테이너 1개씩)
        │ 신원       │        │ 신원       │        │ 신원       │
        └───────────┘        └───────────┘        └───────────┘
                         한 대의 머신
```

> 범위: Crewdock은 "채팅으로 말 거는 상주 AI 비서" 호스팅 도구입니다. 임의의 웹앱·DB 같은 일반 컨테이너 호스팅 도구는 아닙니다.

## 빠른 시작 (로컬)

전제조건 없이 — 게이트웨이도, Tailscale도, OAuth도 필요 없습니다. **클론한 폴더 안에서 그대로** 비서 하나를 바로 띄웁니다.

```bash
# 1) 클론 + 의존성 설치 (이 폴더가 이 배포의 홈이자 데이터 루트)
git clone https://github.com/hungryoon/crewdock ~/my-crew
cd ~/my-crew
uv sync

# 2) 이 배포 초기화 (프로젝트 이름 지정, 1회). CREW_ROOT 불필요 — 현재 폴더가 루트
#    출력에 고유 id가 표시됩니다 (예: my-crew-fox42) — 컨테이너는 `my-crew-fox42-...`
uv run crew init my-crew

# 3) 격리된 인스턴스 생성 (기본 타입: hermes). 포트는 자동 배정됩니다.
uv run crew create alice

# 4) 상태 확인 — 대시보드 URL이 표시됩니다 (예: http://127.0.0.1:9120/)
uv run crew status alice

# 5) 모델 연결 — 컨테이너 안에서 provider 로그인
uv run crew shell alice
#   (컨테이너 내부에서) hermes auth add <provider>   예: openai-codex, anthropic
```

이제 표시된 루프백 URL을 이 컴퓨터에서 열면 비서의 대시보드가 뜹니다.

- 모든 런타임 상태(인스턴스·시크릿·게이트웨이 등)는 이 폴더의 **gitignore된 `data/` 한곳**(`data/_shared.env`, `data/instances/<name>/`, `data/credentials/`, `data/layers/`, `data/_gateway/`)에 쌓입니다. 추적되는 코드·설정(`crew/`, `agents/`, `seed/`, `_shared.env.example`)은 최상위에 그대로 남습니다. 코드 업데이트(`git pull`)는 데이터를 건드리지 않아 안전합니다. (단 `git clean -dfx` 는 gitignore된 데이터까지 지우니 피하세요.)
- **백업·이전 = `data/` 폴더 하나만 복사**하면 됩니다.
- 둘째 인스턴스는 다음 빈 포트를 자동으로 받습니다(겹치지 않음).
- **둘째 배포**가 필요하면 다른 폴더에 또 clone하고 다른 프로젝트 이름으로 `crew init <other> --https-port 8443` — 네임스페이스로 한 머신에서 공존합니다.

> ⚠️ Crewdock은 **소스 클론에서 실행**합니다(`uv sync` 후 `uv run crew …`). `pip install` / `uv tool install` 같은 설치형은 게이트웨이가 도커 이미지를 빌드할 때 소스 트리를 못 찾아 `crew gateway up` 이 실패합니다. (운영 배포는 활성 개발 체크아웃이 아니라 **전용 clone**에서 돌리세요.)

## 핵심 개념

- **인스턴스(instance)** — 비서 한 "명". 격리된 Docker 컨테이너 1개 + 전용 `data/` 폴더. 기억·세션·키·신원이 모두 분리됩니다.

- **배포(deployment)** — 배포 디렉터리 하나가 한 배포입니다(`crew` 는 현재 폴더에서 위로 올라가며 배포 마커인 `data/_shared.env` 가 있는 가장 가까운 폴더를 배포 루트로 잡습니다 — 환경변수 불필요). 모든 런타임 상태는 그 폴더의 **gitignore된 `data/` 한곳**에 모이고(추적 코드·설정은 최상위에 남음), **백업·이전은 `data/` 폴더 하나만 복사**하면 됩니다. `crew init` 이 프로젝트 이름(`CREW_PROJECT`)과 게이트웨이 포트를 정하는데, 이때 **고유 접미사가 붙은 id**를 배정합니다(예: `crew init synt` → `synt-fox42`, init 출력에 표시). 모든 Docker 객체는 그 id로 prefix됩니다(`synt-fox42-alice`, `synt-fox42-gateway-router` …). 덕분에 **이름이 같은 두 배포가 다른 폴더에 있어도 절대 충돌하지 않고**, `prod`·`smoke` 같은 **여러 배포가 한 머신에서 동시에 공존**합니다(이름·포트가 겹치면 조용히 덮어쓰지 않고 에러로 막습니다).

- **데이터 레이어(layer)** — 여러 비서가 공유할 자료(문서·가이드·브랜드 톤)를 **읽기 전용**으로 주입합니다. `data/layers/<이름>/` 폴더를 만들고 `crew create alice --layer knowledge` 로 마운트하면, 비서는 읽되 고칠 수 없습니다. 기본은 "아무 레이어도 안 붙음".

- **자격증명 번들(credential)** — 공통 API 키를 `credentials/<이름>.env` 파일로 묶어 `crew create alice --credential anthropic` 로 주입합니다. 값은 compose 파일에 박히지 않고 런타임에 읽힙니다. (텔레그램 등 메신저 연동은 옵션이며 기본 비활성 — 토큰이 필요하면 이 번들로 주입하면 됩니다.)

- **모델 셋업** — LLM provider 로그인(OAuth/API)은 Crewdock이 아니라 Hermes가 담당합니다. 두 경로가 있습니다: ① 게이트웨이 대시보드의 **브라우저 내 모델 셋업 UI**, ② `crew shell <name>` 후 `hermes auth add <provider>`.

- **접근 제어** — 인스턴스는 기본적으로 게이트웨이에 게시됩니다. 누가 보고 접근하느냐는 인스턴스별 `CREW_ALLOWED_EMAILS`(`data/instances/<name>/instance.env`)로만 결정됩니다. 비어 있으면 **아무에게도 안 보이고 접근 불가**(fail-closed)이며, 각 사용자는 자기 이메일이 든 인스턴스만 봅니다.

## 팀에 공개하기 (게이트웨이)

`crew gateway up` 을 하면 **하나의 게이트웨이**가 **두 URL**로 열립니다:

- **팀 뷰** `https://<타일넷>/` — Tailscale + 구글 SSO(oauth2-proxy). 각 사용자는 **자기 이메일이 허용된 인스턴스만** 봅니다. 외부·원격 사용자(팀·고객)용.
- **로컬 뷰** `http://127.0.0.1:9402/` — 로그인 없이(호스트 접근 = 운영자), **전체 인스턴스**를 봅니다. 호스트에서 직접 쓰는 운영자용.

둘 다 `crew gateway up` 으로 함께 뜨고 `crew gateway down` 으로 함께 내려갑니다. `crew gateway open` 으로 로컬 뷰를 브라우저에서 바로 엽니다(게이트웨이가 떠 있어야 함). 로컬 뷰 포트는 `CREW_GATEWAY_LOCAL_PORT`(기본 9402)로 바꿀 수 있습니다.

> **로컬 뷰만 쓸 거면 화이트리스트가 없어도 됩니다.** `crew gateway up` 은 허용 이메일이 하나도 없어도 (경고만 띄우고) 켜지며, 로컬 뷰는 바로 쓸 수 있습니다. 팀 뷰(SSO)는 화이트리스트가 채워질 때까지 아무도 들이지 않습니다.

```bash
# 0) 팀 뷰(SSO)를 쓸 거면 먼저 구글 OAuth 클라이언트를 설정
#    data/_shared.env 에 CREW_GOOGLE_CLIENT_ID / CREW_GOOGLE_CLIENT_SECRET
#    (로컬 뷰만 쓸 거면 생략 가능)

# 1) 허용할 구글 계정을 인스턴스에 설정 (팀 뷰에서 쓰임)
#    data/instances/alice/instance.env:
#    CREW_ALLOWED_EMAILS=you@example.com,colleague@example.com

# 2) 게이트웨이 시작 (최초 1회) — 팀/로컬 URL + 등록할 OAuth 리디렉트 URI 출력
crew gateway up

# 3) 화이트리스트를 손으로 바꾼 뒤에는 허용목록 갱신
crew gateway reload

# 4) 호스트에서 로컬 뷰(전체 인스턴스) 바로 열기
crew gateway open
```

팀 뷰: 사용자가 게이트웨이 URL에 접속 → 구글 로그인 → 이메일이 허용된 인스턴스의 대시보드로 프록시됩니다. 로컬 뷰: 운영자가 `crew gateway open` 으로 로그인 없이 전체 인스턴스를 봅니다. 둘째 배포(예: 스모크용)는 다른 폴더에 또 clone하고 거기서 `crew init smoke --https-port 8443` 으로 상용과 동시에 띄울 수 있습니다. (포트가 겹치면 `--router-port`/`--auth-port`/`--local-port` 로도 조정 가능.)

> 📘 인프라 셋업 → 사용자 추가 → 운영 → 보안 모델 → 트러블슈팅 전체 절차는 **[docs/multi-user.md](docs/multi-user.md)** 를 참고하세요.

## 명령어 레퍼런스

| 명령어 | 설명 |
| --- | --- |
| `crew init <project>` | 현재 폴더를 새 배포로 초기화 (1회). 프로젝트 이름·포트 설정, 디렉터리 스캐폴딩 |
| `crew create <name>` | 격리된 인스턴스 생성 (옵션 ↓) |
| `crew list` | 전체 인스턴스 목록 |
| `crew status <name>` | 상태·타입·이미지·대시보드 URL (롤백 가능한 이전 이미지 표시) |
| `crew logs <name>` | 컨테이너 로그 (`-f`/`--follow` 로 실시간) |
| `crew start` / `stop` / `restart` `<name>` | 인스턴스 시작·정지·재시작 |
| `crew update <name>` | 설정 반영 + 이미지 핀 관리 (옵션 ↓) |
| `crew shell <name>` | 컨테이너 내부 셸 접속 (모델 인증도 여기서) |
| `crew layers` | 사용 가능한 읽기 전용 데이터 레이어 목록 |
| `crew credentials` | 자격증명 번들 목록 (키 이름만, 값은 표시 안 함) |
| `crew gateway up` / `down` / `reload` / `open` | 단일 로그인 게이트웨이 시작·중지·허용목록 갱신·로컬 뷰 열기 |
| `crew rm <name>` | 인스턴스 제거 (`--purge` 없으면 **데이터 보존**) |

**`crew create` 옵션**

| 옵션 | 설명 |
| --- | --- |
| `--type` | 에이전트 타입 (기본 `hermes`). `agents/<type>.yaml` 매니페스트에서 정의 |
| `--layer` | 마운트할 읽기 전용 데이터 레이어 (반복 가능) |
| `--credential` | 주입할 자격증명 번들 (반복 가능) |
| `--timezone` / `--tz` | 컨테이너 타임존 (IANA, 기본 `Asia/Seoul`) |

## 이미지 버전 관리

에이전트 타입의 기본 이미지는 매니페스트(`agents/<type>.yaml`)에 태그 또는 `@sha256:` 다이제스트로 고정됩니다. 인스턴스마다 **독립적인 이미지 핀**을 가집니다.

```bash
crew update alice                  # 현재 핀으로 재렌더 + pull + 재시작 (버전 무변경)
crew update alice --image <ref>    # 특정 버전으로 핀 변경 (태그 또는 @sha256:...)
crew update alice --rollback       # 직전 이미지로 복원
crew update alice --to-default     # 매니페스트 기본 이미지로 복원
crew update alice --tz UTC         # 인스턴스 타임존 변경 (재렌더 + 재시작)
crew update --all [--backup]       # 전체 인스턴스 업데이트 (--backup: data/ 스냅샷)
```

`--image` / `--rollback` / `--to-default` 는 배타적입니다. 핀 변경 중 pull/up 실패 시 `meta.json` 과 `docker-compose.yml` 이 **원자적으로 복원**되어 중간 상태가 남지 않습니다.

## 한계와 주의

- **인스턴스 격리는 브리지 네트워킹 + 게이트웨이 SSO 로** — 각 인스턴스는 자기만의 브리지 네트워크에서 돌아 게이트웨이 라우터(호스트 루프백)나 다른 인스턴스에 닿을 수 없습니다. 따라서 접근 경계는 게이트웨이의 SSO + 인스턴스별 이메일 화이트리스트입니다. "완벽히 안전"이 아니라 "브리지 격리 + 게이트웨이 SSO"로 막는다는 뜻입니다.
- **브라우저 내 대시보드 인증은 게이트웨이가 담당** — 잠긴 컨테이너 안에서 Hermes 자체 대시보드 인증 게이트는 의도적으로 꺼져 있습니다(`HERMES_DASHBOARD_INSECURE=1`). 호스트 publish가 루프백 전용(`127.0.0.1`)이고 인스턴스가 브리지로 격리돼 있어, 실제 인증은 앞단 게이트웨이 SSO가 맡습니다.
- **단일 머신 · 단일 운영자 전제** — `crew` CLI를 쓸 수 있는 사람의 권한 분리(RBAC)는 없습니다. CLI 접근 권한 = 모든 인스턴스 조작 가능.
- **헬스체크는 "대시보드 생존성"까지만** — `status` 가 초록이어도 비서의 메신저 연결까지 보장하진 않습니다.
- **자원 한도(mem/cpus)는 CLI 플래그가 아니라 매니페스트**(`agents/<type>.yaml`)에서 설정합니다.
- **업데이트는 in-place 재생성**입니다 — 이미지가 데이터 포맷을 바꾸는 경우를 대비해 `crew update --backup` 으로 `data/` 스냅샷을 남길 수 있습니다(마이그레이션은 사용자 책임).

## 라이선스

MIT
