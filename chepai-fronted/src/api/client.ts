import axios from 'axios'

const TOKEN_KEY = 'chepai_token'
const USER_KEY = 'chepai_user'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? ''

export const http = axios.create({
  baseURL,
  timeout: 30_000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status as number | undefined
    const url = String(err.config?.url ?? '')
    if (status === 401 && !url.includes('/api/auth/login')) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    const data = err.response?.data as
      | { error?: string; message?: string; detail?: string }
      | undefined
    const msg =
      data?.error ?? data?.detail ?? data?.message ?? err.response?.statusText ?? err.message ?? '请求失败'
    return Promise.reject(new Error(msg))
  },
)

/** 将库中 snapshotPath 转为可在浏览器打开的 URL */
export function snapshotUrl(path: string | null | undefined): string | null {
  if (!path) return null
  if (path.startsWith('/api/snapshots/')) {
    const root = baseURL.replace(/\/$/, '')
    const token = localStorage.getItem(TOKEN_KEY) ?? ''
    const q = token ? `?access_token=${encodeURIComponent(token)}` : ''
    return `${root}${path}${q}`
  }
  return null
}

export const VOICE_ALERT_TYPES = [
  { value: 'oil_car', label: '燃油车' },
  { value: 'bad_park', label: '未停正' },
  { value: 'mini_ad', label: '小广告' },
  { value: 'dual_slot', label: '占两车位' },
  { value: 'car_in_bus_slot', label: '轿车占公交位' },
  { value: 'bus_in_restricted', label: '公交进限制区' },
] as const

export type Site = {
  id: number
  name: string
  address: string | null
  createdAt: string
}

export type Camera = {
  id: number
  siteId: number
  name: string
  rtspUrl: string | null
  channelNo: number | null
  edgeBoxId: string | null
  createdAt: string
}

export type RoiRegion = {
  id: number
  cameraId: number
  regionType: string
  name: string | null
  polygonJson: string
  createdAt: string
}

export type Alert = {
  id: number
  cameraId: number
  alertType: string
  score: number | null
  snapshotPath: string | null
  rawJson: unknown
  createdAt: string
}

export type PageResult<T> = {
  content: T[]
  total: number
  page: number
  size: number
}

export type AppUser = {
  id: number
  username: string
  displayName: string | null
  role: 'SUPER_ADMIN' | 'USER'
  enabled: boolean
  createdAt: string
  features?: string[]
}

export type EdgeBox = {
  id: string
  name: string
  createdAt: string
  lastSeenAt: string | null
  hostname: string | null
  agentVersion: string | null
  cameraCount: number | null
  online: boolean
  status: {
    cameras?: { id: number; alive: boolean; grabAgeSec: number | null; analyzeAgeSec: number }[]
    loadavg?: number[] | null
    disk?: { totalGb: number; freeGb: number }
  } | null
}

export type EdgeLog = {
  id: number
  edgeBoxId: string
  source: string
  body: string
  collectedAt: string
  createdAt: string
}

export type VoiceClip = {
  edgeBoxId: string
  alertType: string
  originalName: string | null
  sha256: string
  updatedAt: string
}

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function getStoredUser(): AppUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AppUser
  } catch {
    return null
  }
}

export function storeSession(token: string, user: AppUser) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export async function login(username: string, password: string) {
  const { data } = await http.post<{ token: string; user: AppUser }>('/api/auth/login', {
    username,
    password,
  })
  storeSession(data.token, data.user)
  return data
}

export async function fetchMe() {
  const { data } = await http.get<AppUser>('/api/auth/me')
  localStorage.setItem(USER_KEY, JSON.stringify(data))
  return data
}

export async function logout() {
  try {
    await http.post('/api/auth/logout')
  } catch {
    /* ignore */
  }
  clearSession()
}

export async function fetchUsers() {
  const { data } = await http.get<AppUser[]>('/api/users')
  return data
}

export async function createUser(payload: {
  username: string
  password: string
  displayName?: string | null
  role?: 'USER' | 'SUPER_ADMIN'
}) {
  const { data } = await http.post<{ id: number }>('/api/users', payload)
  return data
}

export async function updateUser(
  id: number,
  payload: { displayName?: string | null; password?: string; enabled?: boolean },
) {
  await http.put(`/api/users/${id}`, payload)
}

export async function fetchEdgeBoxes() {
  const { data } = await http.get<EdgeBox[]>('/api/edge-boxes')
  return data
}

export async function fetchEdgeBoxLogs(edgeBoxId: string, limit = 10) {
  const { data } = await http.get<EdgeLog[]>(
    `/api/edge-boxes/${encodeURIComponent(edgeBoxId)}/logs`,
    { params: { limit } },
  )
  return data
}

export async function fetchUserEdgeBoxes(userId: number) {
  const { data } = await http.get<EdgeBox[]>(`/api/users/${userId}/edge-boxes`)
  return data
}

export async function assignUserEdgeBoxes(userId: number, edgeBoxIds: string[]) {
  await http.put(`/api/users/${userId}/edge-boxes`, { edgeBoxIds })
}

export async function fetchUserFeatures(userId: number) {
  const { data } = await http.get<string[]>(`/api/users/${userId}/features`)
  return data
}

export async function assignUserFeatures(userId: number, features: string[]) {
  await http.put(`/api/users/${userId}/features`, { features })
}

export async function fetchVoiceClips(edgeBoxId: string) {
  const { data } = await http.get<VoiceClip[]>('/api/voice', { params: { edgeBoxId } })
  return data
}

export async function uploadVoice(edgeBoxId: string, alertType: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<VoiceClip>('/api/voice', form, {
    params: { edgeBoxId, alertType },
    timeout: 60_000,
  })
  return data
}

export async function fetchVoiceBlob(edgeBoxId: string, alertType: string) {
  const { data } = await http.get<Blob>(`/api/voice/file/${encodeURIComponent(edgeBoxId)}/${alertType}`, {
    responseType: 'blob',
  })
  return data
}

export async function fetchSites() {
  const { data } = await http.get<Site[]>('/api/sites')
  return data
}

export async function createSite(payload: { name: string; address?: string | null }) {
  await http.post('/api/sites', payload)
}

export async function fetchCameras(siteId?: number | null) {
  const { data } = await http.get<Camera[]>('/api/cameras', {
    params: siteId != null ? { siteId } : {},
  })
  return data
}

export async function createCamera(payload: {
  siteId: number
  name: string
  rtspUrl?: string | null
  channelNo?: number | null
  edgeBoxId?: string | null
}) {
  await http.post('/api/cameras', payload)
}

export async function updateCamera(
  id: number,
  payload: {
    name: string
    rtspUrl?: string | null
    channelNo?: number | null
    edgeBoxId?: string | null
  },
) {
  await http.put(`/api/cameras/${id}`, payload)
}

export async function fetchRois(cameraId: number) {
  const { data } = await http.get<RoiRegion[]>('/api/rois', { params: { cameraId } })
  return data
}

export async function createRoi(payload: {
  cameraId: number
  regionType: string
  name?: string | null
  polygonJson: string
}) {
  await http.post('/api/rois', payload)
}

export async function fetchAlerts(params: {
  cameraId?: number
  type?: string
  from?: string
  to?: string
  page?: number
  size?: number
}) {
  const { data } = await http.get<PageResult<Alert>>('/api/alerts', { params })
  return data
}
