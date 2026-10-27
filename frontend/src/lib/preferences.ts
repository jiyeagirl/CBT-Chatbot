const ONBOARDED_KEY = 'synap.onboarded'
const SAVE_HISTORY_KEY = 'synap.saveHistory'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 저장소를 쓸 수 없는 환경(사생활 보호 모드 등)에서는 세션 동안만 유지된다.
  }
}

export const isOnboarded = () => read(ONBOARDED_KEY) === '1'
export const completeOnboarding = (saveHistory: boolean) => {
  write(ONBOARDED_KEY, '1')
  write(SAVE_HISTORY_KEY, saveHistory ? '1' : '0')
}
