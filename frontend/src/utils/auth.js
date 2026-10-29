/**
 * 认证工具：HMAC 签名会话令牌 & 用户展示信息
 *
 * token 由服务端用 AUTH_SECRET 签发（v1.<b64>.<sig>），前端不能篡改。
 * 客户端只持有 token + 展示用的 user_info。
 */

const STORAGE_KEY = 'mc_auth_token'
const USER_INFO_KEY = 'mc_user_info'

/**
 * 读取登录 token（HMAC 签名）
 */
export function getAuthToken() {
  return localStorage.getItem(STORAGE_KEY)
}

/**
 * 保存登录 token 与展示用 user_info
 */
export function setAuthSession(token, userInfo) {
  localStorage.setItem(STORAGE_KEY, token)
  if (userInfo) {
    localStorage.setItem(USER_INFO_KEY, JSON.stringify(userInfo))
  }
}

/**
 * 仅清掉 token（user_info 一并清）
 */
export function clearAuthSession() {
  localStorage.removeItem(STORAGE_KEY)
  localStorage.removeItem(USER_INFO_KEY)
}

/**
 * 读取展示用 user_info（仅供前端显示用户名/部门，无安全意义）
 */
export function getUserInfo() {
  const raw = localStorage.getItem(USER_INFO_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/**
 * 检查会话是否过期：服务端验签失败/过期时也会 401，这里只是客户端预判
 */
export function isSessionExpired() {
  // token 本身没有 exp 字段暴露给前端，让后端校验决定；这里只检查是否有 token
  return !getAuthToken()
}

/**
 * 登出
 */
export function logout() {
  clearAuthSession()
}