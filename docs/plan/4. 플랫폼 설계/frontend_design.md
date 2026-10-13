# 프론트엔드 설계 (React + TypeScript)

## 1. 기술 스택

| 분류 | 선택 | 이유 |
|------|------|------|
| UI 프레임워크 | React 18 + TypeScript | 컴포넌트 재사용, 타입 안전 |
| 빌드 도구 | Vite | 빠른 HMR, ESM 네이티브 |
| 라우터 | React Router v6 | SPA 라우팅 |
| 서버 상태 | TanStack Query v5 | 캐시, 자동 재요청, 무효화 |
| 클라이언트 상태 | Zustand | JWT/사용자 세션, 전역 UI 상태 |
| UI 컴포넌트 | shadcn/ui + Radix UI | 접근성, 커스터마이즈 용이 |
| 스타일 | Tailwind CSS | 유틸리티 클래스, 디자인 토큰 |
| WebSocket | 네이티브 WebSocket API | 문서 처리 진행률 구독 |
| HTTP 클라이언트 | Axios | 인터셉터로 JWT 자동 첨부 |

---

## 2. 라우트 구조

```
/                          → 리다이렉트 → /dashboard
/login                     → 로그인 페이지
/dashboard                 → 대시보드 (최근 문서, 통계)
/documents                 → 문서 목록
/documents/upload          → 문서 업로드 (단일 파일 또는 ZIP bulk, task #62)
/documents/:id             → 문서 상세 (처리 상태, 리뷰 대기 알림, 청크 hit-count 배지 task #58)
/documents/:id/review      → 리뷰 & 정제 워크플로우 (REVIEW_PENDING 상태)
/collections               → 컬렉션 목록
/collections/new           → 컬렉션 생성
/collections/:id           → 컬렉션 상세 (문서 목록, 통계, 임베딩 모델 변경 시 배경 재임베딩 상태 task #63, 골든 쿼리 평가 모달 task #64)
/collections/:id/search    → 컬렉션 내 벡터 검색
/search                    → 전체 검색
/admin/users               → 사용자 관리 (admin 전용)
/admin/system              → 시스템 통계 (admin 전용)
```

---

## 3. 페이지별 설계

### 3-1. 대시보드 (`/dashboard`)

**목적:** 시스템 상태 한눈에 파악

```
┌────────────────────────────────────────────────┐
│  📊 요약 카드 (4개, 수평 배치)                   │
│  [전체 문서] [인덱싱 완료] [처리 중] [실패]       │
├────────────────────────────────────────────────┤
│  📋 최근 처리 문서 (최근 10개)                   │
│  파일명 | 상태 | 컬렉션 | 처리 시간 | 업로드 시각  │
│  (상태별 배지 색상: 진행=파랑, 완료=녹색, 실패=빨강)│
├────────────────────────────────────────────────┤
│  📚 컬렉션 요약 (카드 그리드)                    │
│  각 컬렉션: 이름 | 문서 수 | 벡터 수 | 마지막 인덱싱│
└────────────────────────────────────────────────┘
```

**데이터 소스:**
- `GET /api/v1/documents?limit=10&sort=created_at_desc`
- `GET /api/v1/collections`
- 5초 주기 자동 갱신 (`refetchInterval: 5000`)

---

### 3-2. 문서 목록 (`/documents`)

```
┌────────────────────────────────────────────────┐
│  [업로드] 버튼              [검색창] [필터] [정렬]│
├────────────────────────────────────────────────┤
│  필터 바 (상태, 형식, 컬렉션)                    │
├────────────────────────────────────────────────┤
│  문서 카드 목록                                 │
│  ┌──────────────────────────────────────────┐ │
│  │ [파일 아이콘] 파일명.pdf        [상태 배지] │ │
│  │ 크기 | 형식 | 업로드: 2026-06-30          │ │
│  │ 컬렉션: 법령자료 | 청크: 245개            │ │
│  │ [상세 보기] [재처리] [삭제]               │ │
│  └──────────────────────────────────────────┘ │
├────────────────────────────────────────────────┤
│  페이지네이션                                   │
└────────────────────────────────────────────────┘
```

**REVIEW_PENDING 문서:** 배지에 "리뷰 필요" 표시, 카드 상단에 노란 강조선

---

### 3-3. 문서 상세 (`/documents/:id`)

```
┌────────────────────────────────────────────────┐
│  ← 목록으로      파일명.pdf        [상태 배지]   │
├──────────────────────┬─────────────────────────┤
│ 처리 진행 타임라인    │ 문서 메타데이터            │
│                      │ 파일 크기, 형식, SHA256   │
│ ● 인입 완료          │ 페이지 수, 언어           │
│ ● 파싱 완료          │ 품질 점수                │
│ ● 구조화 완료        │ 총 블록/청크 수           │
│ ⏳ 리뷰 대기 (현재)  ├─────────────────────────┤
│ ○ 정제              │ 컬렉션                   │
│ ○ 정규화            │ 임베딩 모델               │
│ ○ 청킹              │ 인덱싱 시각               │
│ ○ 임베딩            ├─────────────────────────┤
│ ○ 업로드            │ 내보내기                 │
│                      │ [canonical_json ▼]      │
│ [리뷰 시작 →]        │ [내보내기 생성]           │
└──────────────────────┴─────────────────────────┘
```

**REVIEW_PENDING 상태:** "리뷰 시작 →" 버튼 활성화, 클릭 시 `/documents/:id/review`로 이동

**실패 상태:** 에러 코드, 에러 메시지 노출 + [재처리] 버튼

---

### 3-4. 리뷰 & 정제 워크플로우 (`/documents/:id/review`)

가장 복잡한 페이지. 사용자가 StructuredDocument의 블록을 검토하고 정제 명령어를 제출한다.

```
┌──────────────────────────────────────────────────────────┐
│  ← 문서 상세      파일명.pdf 리뷰         [제출] [취소]   │
├──────────────────────────────────────────────────────────┤
│              낮은 신뢰도 블록: 3개 남음                   │
│  ● blk_0042  ● blk_0043  ● blk_0045                     │
├────────────────────────────┬─────────────────────────────┤
│  원본 문서 뷰               │  정제 명령어 패널           │
│                            │                             │
│  [섹션 트리 - 좌측]         │  현재 선택: blk_0042        │
│   ▶ 1장 계약 당사자         │  블록 내용:                 │
│     ▶ 1.1 임차인            │  "본 계약은 2024년..."      │
│     ▶ 1.2 임대인            │                             │
│   ▶ 2장 목적물              │  현재 분류: paragraph       │
│                            │  신뢰도: 0.62 (낮음)        │
│  [블록 목록 - 우측]         │                             │
│  blk_0040 heading ✓        │  [역할 변경  ▼ heading    ] │
│  blk_0041 paragraph ✓      │  [블록 제거               ] │
│  ▶ blk_0042 paragraph ⚠   │  [텍스트 수정             ] │
│  ▶ blk_0043 table ⚠        │                             │
│  blk_0044 paragraph ✓      │  ─────────────────────     │
│                            │  추가된 명령어 (2개)         │
│  블록 상세:                 │  ✓ blk_0042: 역할→heading  │
│  "본 계약은 2024년..."      │  ✗ blk_0043: 제거           │
│                            │                             │
│  [이전] [다음 저신뢰도]      │  [모두 지우기]              │
└────────────────────────────┴─────────────────────────────┘
```

**핵심 인터랙션:**
1. 좌측 블록 클릭 → 우측 패널에 해당 블록 정보 표시
2. 우측에서 명령어 선택 → 명령어 목록에 추가 (즉시 저장 없음)
3. "제출" 클릭 → `POST /api/v1/documents/:id/refinements` → 202 응답 → 처리 시작
4. WebSocket `/ws/documents/:id/progress` 구독으로 진행률 실시간 표시

**테이블 블록 특수 처리:**
- 테이블 미리보기 렌더링
- 헤더 행 수 지정 컨트롤 (`table_header_override`)
- 셀 병합 시각적 표시

---

### 3-5. 컬렉션 상세 (`/collections/:id`)

```
┌────────────────────────────────────────────────┐
│  컬렉션 이름                    [검색] [설정]   │
│  임베딩: bge_m3 | 차원: 1024 | Cosine          │
├──────────────────┬─────────────────────────────┤
│  통계             │ 문서 목록                   │
│  문서: 150        │ [문서 추가] [필터]           │
│  청크: 24,500     │                             │
│  벡터: 24,500     │ 문서명 | 청크 수 | 인덱싱 시각│
│  상태: 정상       │ 법령_2024.pdf | 245 | ...   │
│                  │ 계약서.docx | 88 | ...      │
└──────────────────┴─────────────────────────────┘
```

---

### 3-6. 검색 (`/collections/:id/search`)

```
┌────────────────────────────────────────────────┐
│  [검색창: 임차인의 보증금 반환 의무...    [검색]]│
│  필터: 청크 유형▼  언어▼  최소 품질▼  페이지▼  │
├────────────────────────────────────────────────┤
│  검색 결과 (10개, 45ms)                         │
│  ┌──────────────────────────────────────────┐ │
│  │ 유사도: 0.924                [문서로 이동] │ │
│  │ 주택임대차보호법 › 제3조의2              │ │
│  │ (보증금의 회수) pp.5                     │ │
│  │                                          │ │
│  │ "임대인은 임대차가 종료된 경우에..."      │ │
│  └──────────────────────────────────────────┘ │
│  (결과 카드 반복)                               │
└────────────────────────────────────────────────┘
```

**검색 결과 카드:**
- 유사도 점수 (색상 그라디언트: 녹색=높음, 노란=중간)
- 섹션 경로 (브레드크럼)
- 청크 텍스트 미리보기 (최대 200자)
- 원본 문서/페이지 링크

---

## 4. 컴포넌트 계층

```
App
├── AuthProvider (Zustand: 로그인 상태, JWT)
├── QueryClientProvider (TanStack Query)
├── Layout
│   ├── Sidebar
│   │   ├── NavItem (대시보드, 문서, 컬렉션, 검색)
│   │   └── UserMenu (역할 표시, 로그아웃)
│   └── MainContent
│       └── [Route별 페이지]
│
├── 공통 컴포넌트
│   ├── DocumentStatusBadge
│   ├── ProgressTimeline
│   ├── ProcessingProgressBar (WebSocket 연결)
│   ├── FileFormatIcon
│   └── CollectionCard
│
└── 도메인 컴포넌트
    ├── review/
    │   ├── ReviewWorkflow (메인 컨테이너)
    │   ├── BlockList (좌측 블록 목록)
    │   ├── BlockDetail (우측 블록 상세)
    │   ├── OperationPanel (명령어 선택 패널)
    │   ├── OperationList (추가된 명령어 목록)
    │   └── TablePreview
    ├── search/
    │   ├── SearchBar
    │   ├── SearchFilters
    │   └── SearchResultCard
    └── collections/
        ├── CollectionStats
        └── EmbeddingModelBadge
```

---

## 5. 상태 관리

### 5-1. 전역 상태 (Zustand)

```typescript
interface AuthStore {
  user: User | null;
  accessToken: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshToken: () => Promise<void>;
}

interface UIStore {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}
```

### 5-2. 서버 상태 (TanStack Query)

```typescript
// 문서 목록
useDocuments(filters: DocumentFilters)

// 문서 상세 + 5초 자동 갱신 (처리 중인 문서)
useDocument(id: string, { refetchInterval: isProcessing ? 5000 : false })

// 리뷰 번들 (정제 페이지에서 사용)
useReviewBundle(docId: string)

// 컬렉션 목록 및 상세
useCollections()
useCollection(id: string)
useCollectionStats(id: string)
```

### 5-3. 리뷰 로컬 상태

정제 명령어는 제출 전까지 컴포넌트 로컬 상태로만 관리 (서버에 저장 안 함).

```typescript
interface ReviewState {
  selectedBlockId: string | null;
  pendingOperations: RefinementOperation[];
  addOperation: (op: RefinementOperation) => void;
  removeOperation: (index: number) => void;
  clearAll: () => void;
  submit: () => Promise<void>;
}
```

---

## 6. 실시간 진행률 (WebSocket)

```typescript
// ProcessingProgressBar 컴포넌트
function useDocumentProgress(docId: string) {
  const [progress, setProgress] = useState<ProgressMessage | null>(null);

  useEffect(() => {
    const ws = new WebSocket(
      `${WS_BASE_URL}/ws/documents/${docId}/progress`
    );
    ws.onmessage = (e) => setProgress(JSON.parse(e.data));
    ws.onclose = () => { /* 처리 완료 또는 실패 시 문서 쿼리 무효화 */ };
    return () => ws.close();
  }, [docId]);

  return progress;
}
```

**진행 단계별 UI:**
- `ingesting` → "파일 로드 중..."
- `parsing` → "문서 파싱 중..."
- `structuring` → "구조 분석 중..."
- `embedding` → "임베딩 생성 중 (41/64 청크)"
- `uploading` → "Qdrant 업로드 중..."

---

## 7. 인증 처리

```
로그인 폼 → POST /auth/login → accessToken + refreshToken 저장
                                (accessToken: 메모리, refreshToken: httpOnly 쿠키)

API 요청 → Axios 인터셉터 → Authorization: Bearer {accessToken} 자동 첨부

401 응답 → Axios 인터셉터 → POST /auth/refresh → 새 accessToken → 원래 요청 재시도

refreshToken도 만료 → /login 리다이렉트
```

**보안 원칙:**
- `accessToken`은 메모리(Zustand)에만 저장 (localStorage/sessionStorage 금지, XSS 방지)
- `refreshToken`은 `httpOnly` 쿠키로 서버가 설정 (JS 접근 불가)

---

## 8. 접근 권한 처리

```typescript
// 역할 기반 라우트 보호
<ProtectedRoute requiredRole="admin">
  <AdminUsersPage />
</ProtectedRoute>

// 컴포넌트 내 권한 조건 렌더링
const { user } = useAuthStore();
{user?.role !== 'viewer' && <Button>정제 제출</Button>}
```

---

## 9. 에러 처리

- **API 에러:** Axios 인터셉터 → 토스트 알림 (에러 코드 + 메시지)
- **네트워크 오류:** TanStack Query retry (3회, 지수 백오프)
- **403 Forbidden:** "권한이 없습니다" 인라인 메시지
- **500 오류:** 전역 에러 바운더리 → 빈 화면 대신 "오류가 발생했습니다" 안내

---

## 10. 연관 문서

| 문서 | 관계 |
|------|------|
| `api_design.md` | REST 엔드포인트 명세 |
| `platform_overview.md` | 전체 시스템 데이터 흐름 |
| `database_schema.md` | 응답 데이터 구조 원천 |
| `refinement.md` | 정제 명령어 목록 및 의미 |
