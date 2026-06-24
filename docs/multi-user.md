# crewdock 멀티유저 온보딩 (운영자 가이드)

여러 사용자에게 각자의 Hermes 대시보드를 나눠주는 방법. 사용자는 **하나의 게이트웨이 URL**에
구글 로그인으로 접속하고, **자기에게 허용된 인스턴스만** 보고 쓸 수 있다.

```
사용자 브라우저 ──HTTPS(443)──▶ Tailscale ──▶ oauth2-proxy(구글 SSO) ──▶ 라우터 ──▶ 인스턴스 대시보드
                                              │                         │
                                       이메일 화이트리스트 검증      인스턴스별 권한 + 시크릿 검증
```

- 인증: 구글 SSO(oauth2-proxy) + **인스턴스별 이메일 화이트리스트**(fail-closed)
- 격리: 한 인스턴스가 다른 인스턴스를 넘볼 수 없음(공유 시크릿으로 직접 우회 차단)
- 노출 범위: **타일넷 내부만**(공개 인터넷 아님)

> **로컬 뷰(운영자용).** `crew gateway up` 은 팀 SSO URL과 함께 호스트용 **로컬 뷰**도 같이
> 띄운다 — `crew gateway open` 또는 `http://127.0.0.1:<CREW_GATEWAY_LOCAL_PORT>/`(기본 9402).
> 호스트 접근 = 운영자이므로 **구글 로그인 없이 전체 인스턴스**를 본다. 운영자가 호스트에서
> 직접 점검·조작할 때 쓰고, 외부 사용자는 위의 팀 SSO URL을 쓴다.

---

## 0. 배포 초기화 (`crew init` — 배포당 1번만)

한 배포(deployment)는 하나의 데이터 루트(배포 디렉터리)와 하나의 프로젝트 이름(`CREW_PROJECT`)으로
식별된다. `crew init`이 그 루트를 스캐폴딩하고(`data/` 아래로 `instances`/`credentials`/`layers`/
`_gateway`, 추적되는 `agents`/`seed` 템플릿은 git으로 최상위에 있음), `data/_shared.env`에
`CREW_PROJECT` + 게이트웨이 포트 + 쿠키 시크릿 + Google OAuth 자리표시자를 한 번에 써준다.
모든 런타임 상태는 gitignore된 `data/` 한곳에 모이므로 **백업·이전은 `data/` 폴더 하나만 복사**하면
된다. `crew init`은 **현재 폴더**를 루트로 잡고(`git init`처럼), 이후의 다른 명령은 현재 폴더에서
위로 올라가며 배포 마커인 `data/_shared.env`가 있는 가장 가까운 폴더를 배포 루트로 찾는다(환경변수 불필요).

```sh
cd ~/synt-crewdock                   # 배포별 데이터 루트로 이동
crew init synt                       # 현재 폴더를 프로젝트 이름으로 한 번만 초기화
                                     #   → 고유 id 배정 (예: synt-fox42, init 출력에 표시)
```

- `crew init`은 라벨(`synt`)에 **고유 접미사**를 붙여 `CREW_PROJECT`를 배정한다(예: `synt-fox42`,
  init 출력에 표시). 덕분에 이름이 같은 두 배포가 다른 폴더에 있어도 절대 충돌하지 않는다.
- `CREW_PROJECT`(여기선 `synt-fox42`)와 게이트웨이 포트(`CREW_GATEWAY_HTTPS_PORT`=443,
  `CREW_ROUTER_PORT`=9400, `CREW_AUTH_PORT`=9401)는 `data/_shared.env`에 들어가며 **`crew init`이
  한 번 써주면 끝**이다. 이후 명령들은 이 값을 읽어 동작한다.
- 모든 Docker 객체는 그 id로 프리픽스된다: 인스턴스 컨테이너는 `<project>-<instance>`
  (예: `synt-fox42-alice`), 게이트웨이 컨테이너는 `<project>-gateway-{router,auth,broker}`.
- Docker를 건드리는 명령은 루트가 초기화돼 있지 않으면 `NotInitializedError`로 멈춘다
  (먼저 `crew init` 실행).

> **두 번째 배포(예: smoke)를 같은 호스트에 띄우려면** 다른 폴더에 따로 clone하고 거기서
> **다른 프로젝트 이름의 `crew init`**, 그리고 **충돌하지 않는 포트**가 필요하다:
> ```sh
> cd ~/smoke-crewdock                   # 별도 폴더(별도 clone)로 이동
> crew init smoke --https-port 8443     # prod(:443)와 별개 포트
> ```
> 이러면 prod와 smoke가 충돌 없이 나란히 돈다. 이름/포트가 겹치면 `crew gateway up`은
> 기존 것을 덮어쓰지 않고 **에러로 멈춘다**(이미 뜬 게이트웨이 컨테이너, 점유된 포트,
> 이미 서빙 중인 타일넷 HTTPS 포트 모두 거부).

---

## 1. 1회 인프라 셋업 (최초 1번만)

### a. Tailscale (HTTPS)
호스트가 타일넷에 연결되고 MagicDNS + HTTPS 인증서가 켜져 있어야 한다.
```sh
tailscale status          # 호스트가 보이는지
tailscale cert             # (필요시) 타일넷 HTTPS 인증서
```

### b. Google OAuth 클라이언트
Google Cloud Console → "OAuth 2.0 클라이언트 ID" → **웹 애플리케이션** 생성.
- client_id / client_secret 확보
- 리디렉트 URI는 `crew gateway up`이 출력해주는 값을 그대로 등록 (예:
  `https://<host>.ts.net/oauth2/callback`)

### c. `_shared.env` (게이트웨이 공통 설정)
`crew init`이 `data/_shared.env`를 이미 만들고 `CREW_PROJECT`/포트/쿠키 시크릿/OAuth 자리표시자를
써뒀다(`data/_shared.env`, chmod 600). 여기서 OAuth 값만 채운다:
```
CREW_GOOGLE_CLIENT_ID=...apps.googleusercontent.com
CREW_GOOGLE_CLIENT_SECRET=...
CREW_OAUTH_COOKIE_SECRET=     # crew init이 생성해 둠 (필요시 openssl rand -base64 32)
```
> ⚠️ **이메일 화이트리스트는 여기 넣지 않는다.** 화이트리스트는 인스턴스별로만 설정하며,
> `_shared.env`에서 상속되지 않는다(fail-closed).

---

## 2. 사용자 추가 (사용자 1명당 반복)

### ① 인스턴스 생성
```sh
crew create alice                          # 기본: 안정 이미지 핀 + KST
# 옵션:
crew create alice --timezone America/New_York   # 타임존
crew create alice --layer knowledge              # 읽기전용 데이터 레이어
crew create alice --credential anthropic         # 공유 자격증명(API 키) 주입
```

### ② 이메일 화이트리스트 설정 (그 사용자의 구글 계정)
모든 인스턴스는 **생성과 동시에 게이트웨이에 게시된다** — 별도의 노출(expose) 단계는 없다.
접근과 표시 여부는 오직 그 인스턴스의 `CREW_ALLOWED_EMAILS`로만 결정된다.
`data/instances/alice/instance.env` 를 열어 추가(생성 시 주석으로 미리 깔려 있음):
```
CREW_ALLOWED_EMAILS=alice@gmail.com           # 쉼표로 여러 명 가능
```
- 이 인스턴스를 볼 수 있는 계정 목록. **비어 있거나 없으면 게이트웨이에서 보이지 않고 아무도 접근할 수 없다(fail-closed).**
- 사용자는 **자기 이메일이 화이트리스트에 든 인스턴스만** 본다.
- `crew create`로 막 만든 직후라면 게이트웨이 allowlist는 이미 갱신돼 있다. **나중에 손으로 수정한 경우엔**
  `crew gateway reload`로 게이트웨이에 반영한다(oauth2-proxy가 이메일 파일을 watch).

### ③ 게이트웨이 시작 (이미 떠 있으면 새 인스턴스 자동 반영)
```sh
crew gateway up
# 출력되는 리디렉트 URI를 (최초 1번) Google OAuth 클라이언트에 등록
# 출력되는 https://<host>.ts.net/ 를 사용자에게 전달
```

### ④ 모델 인증 (대시보드에서 채팅하려면 필요)
모델/provider 로그인은 운영자가 실행 중 컨테이너에서 한다:
```sh
crew shell alice
# 컨테이너 안에서:
hermes login                  # 또는 hermes auth add <provider> / hermes model
exit
```
또는 **공유 API 키를 크리덴셜로 주입**하면(①의 `--credential`) 로그인 없이 바로 작동한다.

### ⑤ 사용자에게 안내
- URL: `https://<host>.ts.net/`
- 구글 로그인(화이트리스트에 넣은 계정) → 본인 인스턴스 카드 클릭 → 대시보드/채팅
- 외부 메신저 연동(텔레그램 등)은 **기본 꺼짐** — 필요하면 대시보드에서 사용자가 직접 설정

---

## 3. 일상 운영 (Day-2)

| 작업 | 명령 |
|---|---|
| 사용자 추가/제거 | `data/instances/<name>/instance.env`의 `CREW_ALLOWED_EMAILS` 수정 → `crew gateway reload` (게이트웨이 allowlist 갱신) |
| 사용자 접근 회수 / 인스턴스 숨김 | `CREW_ALLOWED_EMAILS`에서 해당 주소 제거 또는 값 비우기 → `crew gateway reload`. 비면 게이트웨이에서 사라지고 아무도 접근 못 함(데이터는 유지) |
| 인스턴스 상태 | `crew status <name>` / `crew list` |
| 설정만 재적용 | `crew update <name>` (버전 불변, `data/_shared.env`·크리덴셜·config 반영) |
| 이미지 업그레이드 | `crew update <name> --image <ref>` 또는 `--to-default` |
| 롤백 | `crew update <name> --rollback` |
| 게이트웨이 중지 | `crew gateway down` |
| 인스턴스 삭제 | `crew rm <name>` (데이터 유지) / `crew rm <name> --purge` (데이터 삭제) |

새 안정 이미지로 전체를 올리려면: `agents/hermes.yaml`의 `image:` digest를 갱신 → `crew update --all`.

---

## 4. 보안 모델 & 신뢰 가정

- **인스턴스별 이메일 화이트리스트** — 모든 인스턴스는 기본 게시되며, 접근/표시 여부는 화이트리스트로만
  통제된다. 라우터가 요청마다 그 인스턴스의 `CREW_ALLOWED_EMAILS`를 확인. 목록에 없으면 403.
  인덱스에도 그 사용자가 허용된 인스턴스만 노출. 화이트리스트가 비면 누구에게도 보이지 않는다(fail-closed).
- **스푸핑 차단** — oauth2-proxy가 공유 시크릿을 Basic-auth로 주입하고 라우터가 검증하므로,
  host 네트워크 인스턴스가 라우터에 직접 붙어 이메일을 위조해도 거부된다(인스턴스 간 횡적 이동 봉쇄).
- **시크릿 취급** — 시크릿 파일 0600 / 디렉토리 0700, 렌더된 compose엔 값 없이 `KEY=${KEY}`만,
  자격증명/런타임 상태는 gitignore.
- **신뢰 가정** — 게이트웨이는 **프라이빗 타일넷 + 신뢰 가능한 호스트 운영자**를 전제로 한다
  (호스트 셸·도커 접근 권한자는 전부 볼 수 있음). 공개 인터넷에 직접 노출하는 용도가 아니다.

---

## 5. 트러블슈팅

- **인스턴스가 게이트웨이에 안 보임** → 그 인스턴스 `instance.env`의 `CREW_ALLOWED_EMAILS`가 비었거나 없음(fail-closed). ①② 참고.
- **로그인은 되는데 인스턴스가 안 보임** → 그 구글 계정이 화이트리스트에 없음. 추가 후 `crew gateway reload`.
- **"events feed disconnected" / 채팅 안 됨** → 보통 브라우저 캐시(옛 세션 토큰). 세션 토큰은 고정돼
  있으니 **새로고침/프라이빗 탭**으로 새로 로드. 그래도면 `crew gateway down && crew gateway up`.
- **채팅에 응답이 없음("Session ended")** → 그 인스턴스에 모델 미인증. ④(`crew shell` → `hermes login`)
  또는 API 키 크리덴셜 주입.
- **구글 로그인 후 리디렉트 에러** → Google OAuth 클라이언트에 `crew gateway up`이 출력한
  리디렉트 URI가 등록됐는지 확인.

---

## 6. 한눈에 (배포 초기화 + 사용자 1명 추가)
```sh
cd ~/synt-crewdock                              # 배포별 데이터 루트로 이동
crew init synt                                  # 배포당 1번 (CREW_PROJECT/포트/_shared.env)
crew create bob --credential anthropic          # 인스턴스 + 모델용 API 키 (생성과 동시에 게시)
echo 'CREW_ALLOWED_EMAILS=bob@gmail.com' >> data/instances/bob/instance.env
crew gateway reload                             # 손으로 고친 화이트리스트를 게이트웨이에 반영
crew gateway up                                 # URL을 bob에게 전달
```

---

## 마이그레이션 (0.4.x → 0.5.0)

0.5.0부터 모든 런타임 상태가 gitignore된 `data/` 한곳으로 모인다. 기존 배포는 코드를 먼저
`git pull`로 새 버전으로 올린 뒤, 배포 폴더 안에서 아래를 그대로 실행한다. **순서가 중요하다** —
`_shared.env`와 `_gateway`를 `instances/` 밖으로 먼저 꺼낸 다음에 `instances/` 자체를 옮긴다:

```bash
# 배포 폴더 안에서 (코드 먼저 git pull 하여 새 버전 받기)
mkdir -p data
mv instances/_shared.env data/_shared.env       2>/dev/null || true
mv instances/_gateway    data/_gateway          2>/dev/null || true
mv instances             data/instances          # 남은 <name>/ 디렉터리
mv credentials           data/credentials        2>/dev/null || true
mv layers                data/layers             2>/dev/null || true
# seed 템플릿은 git으로 seed/ 로 이동됨 — git pull 이후 자동
```

- **`CREW_PROJECT`는 그대로 유지된다** — 고유 접미사는 **새로** `crew init`하는 배포에만 붙고,
  기존 배포의 `data/_shared.env`에 이미 든 `CREW_PROJECT` 값은 건드리지 않는다.
- 이전 릴리즈의 컨테이너/네트워킹 변경으로 기존 컨테이너 재생성이 필요하면
  `crew rm <name> --purge` 후 다시 `crew create` 한다.
