# Crewdock

한 대의 머신에서 **격리된 에이전트 컨테이너 여러 개(crew)** 를 호스팅합니다. 각 인스턴스는
자기만의 Docker 컨테이너·데이터 볼륨·자격증명·대시보드 포트를 가지며, 단일 명령어 `crew`로
전부 관리합니다.

에이전트 종류는 선언적 매니페스트(`agents/*.yaml`)로 정의하므로, 새 런타임(예: OpenClaw)을
추가하려면 매니페스트 하나만 더하면 됩니다. 기본 동봉 타입은 `hermes`입니다.

## 설치

```bash
uv sync
```

모든 명령은 `uv run crew <command>` 형태로 실행합니다.

## 명령어

| 명령어          | 설명                                                          |
| --------------- | ------------------------------------------------------------- |
| `crew create`   | 새 인스턴스 생성 (`--type`, `--bot-token`, `--layer`)          |
| `crew rm`       | 인스턴스 제거 (`--purge` 없으면 데이터 보존)                   |
| `crew list`     | 전체 인스턴스 목록                                            |
| `crew status`   | 한 인스턴스의 컨테이너 상태·포트·헬스 표시                     |
| `crew start`    | 멈춘 인스턴스 시작                                            |
| `crew stop`     | 실행 중 인스턴스 정지                                         |
| `crew restart`  | 인스턴스 재시작                                              |
| `crew logs`     | 컨테이너 로그 (`--follow`)                                     |
| `crew setup`    | 에이전트의 대화형 최초 설정 실행                              |
| `crew update`   | compose 재렌더 + 설정·자격증명 전파 (`--all`, `--backup`)     |
| `crew shell`    | 컨테이너 내부 셸 접속                                         |
| `crew layers`   | 사용 가능한 읽기 전용 데이터 레이어 목록                       |

## 빠른 시작

```bash
crew create alice --type hermes --bot-token <봇토큰> --layer knowledge
crew list
crew status alice          # 대시보드 URL 확인 (예: http://127.0.0.1:9120/)
```

## 자격증명 계층

자격증명은 2단계로 병합됩니다(개별 > 공용).

- **`instances/_shared.env`** — 모든 인스턴스가 공유(예: `HERMES_UID`, `HERMES_GID`,
  매니페스트에서 `inherit_from_shared`로 표시된 공용 LLM 키 등). gitignore 처리되어
  커밋되지 않습니다.
- **`instances/<name>/instance.env`** — 인스턴스별 오버라이드와 필수 비밀값
  (예: 각 인스턴스의 `TELEGRAM_BOT_TOKEN`).

공용 자격증명을 수정한 뒤에는 다음으로 실행 중인 인스턴스에 전파합니다.

```bash
crew update --all
```

각 인스턴스의 compose를 재렌더하고 병합된 환경을 다시 적용합니다.

### LLM 자격증명

`hermes`의 인스턴스별 LLM 인증은 `crew setup`(대화형 OAuth)으로 설정합니다 — 별도의
`--llm-key` 플래그는 없습니다. 공용 기본 키를 쓴다면 `instances/_shared.env`에 둡니다.
자원 한도(mem/cpus)는 CLI 플래그가 아니라 에이전트 매니페스트(`agents/<type>.yaml`)에서
지정합니다.

## 데이터 레이어 (읽기 전용 주입)

레이어는 `layers/` 아래의 **읽기 전용** 공유 디렉토리로, 인스턴스가 골라 마운트합니다.
생성 시 선택합니다.

```bash
crew create alice --type hermes --layer knowledge
crew layers          # 사용 가능한 레이어 목록
```

선택한 레이어는 매니페스트의 `layers_mount` 아래에 읽기 전용으로 마운트됩니다
(예: `layers/knowledge` → `/opt/shared/knowledge:ro`). 따라서 인스턴스는 공유 지식을
**읽을 수만 있고 수정할 수 없습니다.** 기본값은 아무 레이어도 붙지 않음입니다.

## 대시보드 & 접근

각 인스턴스는 관리용 웹 대시보드(설정·API 키·세션)를 이 머신의 고유 **루프백** 포트에
노출합니다 — `crew status <name>`에 URL이 표시됩니다(예: `http://127.0.0.1:9120/`).
`hermes` 타입은 Docker **호스트 네트워킹**(`network_mode: host`)을 써서 대시보드가 호스트의
`127.0.0.1`에 직접 바인딩되고, 헤르메스의 인증 게이트를 그대로 유지합니다(`--insecure` 미사용).

- **대시보드는 의도적으로 루프백 전용입니다** — API 키를 다루므로 LAN/인터넷에 노출하지
  않습니다. 이 머신에서만 열 수 있습니다.
- **다른 머신에서 접근**하려면 SSH 터널을 쓰세요(직접 노출 금지):
  ```bash
  ssh -L 9120:127.0.0.1:9120 you@this-machine   # 이후 원격에서 http://localhost:9120
  ```
- **최종 사용자는 대시보드를 쓰지 않습니다.** 에이전트를 제공받은 사람은 메신저(예: 텔레그램)로
  대화합니다. 대시보드는 운영자 전용입니다.

> 텔레그램: 사용자가 봇과 실제로 대화하게 하려면 인스턴스 설정에서 `TELEGRAM_ALLOWED_USERS`를
> 지정하세요(또는 `GATEWAY_ALLOW_ALL_USERS`로 개방). 기본적으로 미인가 사용자는 거부됩니다.

## 제거 시 데이터 안전

`crew rm <name>`은 컨테이너를 정지·제거하지만 **기본적으로 인스턴스의 데이터 볼륨은
보존**합니다. 데이터까지 삭제하려면 `--purge`를 줍니다.

```bash
crew rm alice            # 컨테이너 제거, instances/alice/data 보존
crew rm alice --purge    # 데이터 디렉토리까지 삭제
```

## 라이선스

MIT
