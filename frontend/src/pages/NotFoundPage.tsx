// 없는 주소로 들어왔을 때 빈 화면 대신 보여 주는 안내.
import { Link, useLocation } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { EmptyState, Page, PageBody, PageHeader, buttonClass } from '../components/ui'

export default function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <Page>
      <PageHeader title="화면을 찾을 수 없습니다" />
      <PageBody>
        <EmptyState
          icon={<Compass size={28} aria-hidden="true" />}
          title={`"${pathname}" 주소에 해당하는 화면이 없습니다`}
          description="주소가 바뀌었거나 잘못 입력되었을 수 있습니다. 왼쪽 메뉴나 Ctrl K(화면 찾기)로 원하는 화면을 찾으세요."
          action={<Link to="/" className={buttonClass('primary', 'sm')}>대시보드로 가기</Link>}
        />
      </PageBody>
    </Page>
  )
}
