import { NavLink } from 'react-router-dom'

const tabs = [
  { to: '/', label: '홈', icon: '🏠' },
  { to: '/records', label: '기록', icon: '📋' },
  { to: '/settings', label: '설정', icon: '⚙️' },
]

export function TabBar() {
  return (
    <nav className="flex justify-between bg-white px-5 pt-2.5 pb-1.5" aria-label="주요 메뉴">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.to === '/'}
          className={({ isActive }) =>
            `flex flex-col items-center gap-0.5 text-[10px] ${
              isActive ? 'font-bold text-primary' : 'text-muted'
            }`
          }
        >
          <span className="text-base text-ink" aria-hidden>
            {tab.icon}
          </span>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
