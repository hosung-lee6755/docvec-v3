// 관리자 문의: 일반 사용자는 자기 문의를, 관리자는 전체 문의를 보고 답한다.
// /inquiries(목록), /inquiries/new(목록 위에 작성 대화상자), /inquiries/:inquiryId(상세).
import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { MessageSquarePlus } from 'lucide-react'
import {
  useInquiries,
  useInquiry,
  useOpenInquiryCount,
  type InquiryListItem,
  type InquiryStatus,
} from '../hooks/useInquiries'
import { useAuthStore } from '../store/authStore'
import { INQUIRY_CATEGORY_LABELS, INQUIRY_STATUS_LABELS } from '../lib/inquiryLabels'
import { formatElapsed } from '../lib/elapsedTime'
import { InquiryComposeModal, type InquiryPrefill } from '../components/inquiries/InquiryComposeModal'
import { InquiryDetailView } from '../components/inquiries/InquiryDetailView'
import {
  Alert, Badge, Button, EmptyState, ErrorAlert, FilterChip, Page, PageBody, PageHeader, Spinner, Stat, StatStrip, Toolbar,
} from '../components/ui'
import type { BadgeTone } from '../components/ui'

const PAGE_SIZE = 20
const STATUS_FILTERS: Array<InquiryStatus | 'all'> = ['all', 'open', 'in_progress', 'resolved', 'closed']
const FILTER_LABELS: Record<InquiryStatus | 'all', string> = { all: '전체', ...INQUIRY_STATUS_LABELS }
const STATUS_TONE: Record<InquiryStatus, BadgeTone> = {
  open: 'info', in_progress: 'warning', resolved: 'success', closed: 'neutral',
}

export default function InquiriesPage() {
  const { inquiryId } = useParams<{ inquiryId: string }>()
  if (inquiryId) return <InquiryDetailPage inquiryId={inquiryId} />
  return <InquiryListPage />
}

function InquiryListPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')
  // 관리자는 아직 답하지 않은 '접수' 문의부터 본다
  const [status, setStatus] = useState<InquiryStatus | 'all'>(isAdmin ? 'open' : 'all')
  const [offset, setOffset] = useState(0)
  const list = useInquiries({ status, limit: PAGE_SIZE, offset })
  const openCount = useOpenInquiryCount(isAdmin)
  const isComposing = location.pathname === '/inquiries/new'
  const prefill = (location.state ?? {}) as InquiryPrefill

  const changeStatus = (next: InquiryStatus | 'all') => {
    setStatus(next)
    setOffset(0)
  }

  const total = list.data?.total ?? 0
  const items = list.data?.items ?? []

  return (
    <Page>
      <PageHeader
        title="관리자 문의"
        subtitle={isAdmin
          ? '직원이 남긴 문의를 확인하고 답합니다. 답변을 시작하면 작성자에게 알림이 갑니다.'
          : '반복되는 오류나 궁금한 점을 관리자에게 남기고, 답변을 여기서 확인합니다.'}
        actions={(
          <Button variant="primary" icon={<MessageSquarePlus size={15} aria-hidden="true" />} onClick={() => navigate('/inquiries/new')}>
            새 문의
          </Button>
        )}
      />
      <StatStrip label="문의 요약">
        <Stat label="표시 중인 문의" value={total} />
        {isAdmin && <Stat label="접수 대기" value={openCount.data?.total ?? 0} tone={(openCount.data?.total ?? 0) > 0 ? 'warning' : 'default'} />}
      </StatStrip>

      <PageBody>
        <Toolbar label="상태 거르기">
          {STATUS_FILTERS.map((value) => (
            <FilterChip key={value} isActive={status === value} onClick={() => changeStatus(value)}>
              {FILTER_LABELS[value]}
            </FilterChip>
          ))}
        </Toolbar>

        {list.isLoading && <Spinner />}
        {list.isError && <ErrorAlert error={list.error} message="문의 목록을 불러오지 못했습니다." onRetry={() => list.refetch()} />}
        {list.data && items.length === 0 && <EmptyState title="문의가 없습니다." description="오류가 반복되면 문서 상세나 실패 화면에서 바로 문의할 수 있습니다." />}
        {items.length > 0 && <InquiryTable items={items} showAuthor={isAdmin} />}

        {total > PAGE_SIZE && (
          <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', marginTop: 'var(--space-3)' }}>
            <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>이전</Button>
            <Button variant="secondary" size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>다음</Button>
          </div>
        )}
      </PageBody>

      <InquiryComposeModal
        isOpen={isComposing}
        prefill={prefill}
        onClose={() => navigate('/inquiries')}
        onCreated={(id) => navigate(`/inquiries/${id}`)}
      />
    </Page>
  )
}

function InquiryTable({ items, showAuthor }: { items: InquiryListItem[]; showAuthor: boolean }) {
  return (
    <div className="ds-table-wrap">
      <table className="ds-table">
        <thead>
          <tr>
            <th scope="col">제목</th>
            <th scope="col">분류</th>
            <th scope="col">상태</th>
            {showAuthor && <th scope="col">작성자</th>}
            <th scope="col">최근 활동</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <Link to={`/inquiries/${item.id}`} className="ds-link-btn">{item.title}</Link>
                {item.document_id && <span className="ds-cell-sub">문서에서 시작한 문의</span>}
              </td>
              <td>{INQUIRY_CATEGORY_LABELS[item.category]}</td>
              <td><Badge tone={STATUS_TONE[item.status]} hasDot>{INQUIRY_STATUS_LABELS[item.status]}</Badge></td>
              {showAuthor && <td>{item.author_name}</td>}
              <td style={{ whiteSpace: 'nowrap' }}>{formatElapsed(item.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function InquiryDetailPage({ inquiryId }: { inquiryId: string }) {
  const navigate = useNavigate()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')
  const { data, isLoading, isError, error, refetch } = useInquiry(inquiryId)

  return (
    <Page>
      <PageHeader
        breadcrumb={<Link to="/inquiries">관리자 문의 목록</Link>}
        title={data?.title ?? '문의'}
        subtitle={data && (
          <span style={{ display: 'inline-flex', gap: 'var(--space-2)', alignItems: 'center' }}>
            <Badge tone={STATUS_TONE[data.status]} hasDot>{INQUIRY_STATUS_LABELS[data.status]}</Badge>
            {INQUIRY_CATEGORY_LABELS[data.category]}
          </span>
        )}
      />
      <PageBody>
        {isLoading && <Spinner />}
        {isError && (
          <ErrorAlert error={error} message="문의를 불러오지 못했습니다. 삭제되었거나 볼 권한이 없을 수 있습니다." onRetry={() => refetch()} />
        )}
        {data && (
          <InquiryDetailView inquiry={data} isAdmin={isAdmin} onDeleted={() => navigate('/inquiries')} />
        )}
        {!data && !isLoading && !isError && <Alert tone="info">문의 정보가 없습니다.</Alert>}
      </PageBody>
    </Page>
  )
}
