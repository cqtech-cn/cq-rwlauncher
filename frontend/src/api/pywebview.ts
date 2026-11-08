/**
 * pywebview 桥接层封装。
 *
 * - 在 WebView 环境下，所有方法直接转发到 window.pywebview.api
 * - 在浏览器（Vite dev）环境下，提供 mock 数据，便于纯前端开发调试
 *
 * ⚠️ pywebview 的 API 是异步注入的（finish.js 中 dispatchEvent 'pywebviewready'
 *    时才把方法挂到 window.pywebview.api），所以所有 call 之前必须先 await
 *    `whenReady()`，否则前端会拿到"方法不可用"的错误。
 */

declare global {
  interface Window {
    pywebview?: { api: any }
  }
}

/* pywebviewready 等待机制
 *
 * pywebview 的 API 注入分两步：
 *   1. api.js 注入 `window.pywebview = { api: {}, ... }`（空 api）
 *   2. finish.js 调 `_createApi(...)` 把方法挂到 api 上，然后 dispatch
 *      'pywebviewready'
 *
 * 这两步都很快（毫秒级），但跨线程时 Vue 的 onMounted 可能在第 1 步前
 * 执行，导致 api 对象存在但方法还没挂上。如果只看 pywebviewready，
 * 也可能因为 page reload 错过事件。
 *
 * 因此 whenReady() 必须在 resolve 之前确保 api 真的"有方法"：
 *   - 轮询 Object.keys(api).length > 0
 *   - 或在 5 秒兜底超时后放行
 */

let readyResolve: (() => void) | null = null
let readyPromise: Promise<void> | null = null

function isApiReady(): boolean {
  if (typeof window === 'undefined') return true
  const api = window.pywebview?.api
  if (!api) return false
  try {
    return Object.keys(api).length > 0
  } catch {
    return false
  }
}

function buildReadyPromise(): Promise<void> {
  if (readyPromise) return readyPromise
  readyPromise = new Promise<void>((resolve) => {
    if (typeof window === 'undefined') {
      resolve()
      return
    }

    // 没有 pywebview（纯浏览器 Vite 调试模式），直接放行
    if (!window.pywebview) {
      resolve()
      return
    }

    // 已经在 onMounted 之前就调 buildReadyPromise
    // 需要等 api 真正"有方法"
    const start = Date.now()
    const maxWait = 6000
    const interval = 50

    const check = () => {
      if (isApiReady()) {
        resolve()
        return
      }
      if (Date.now() - start > maxWait) {
        // 兜底超时：放行（让 call 内部再检查，给出明确报错）
        resolve()
        return
      }
      setTimeout(check, interval)
    }

    // 收到 pywebviewready 后立即检查
    const onReady = () => {
      // 事件触发时 api 刚被填充，立刻 resolve
      // 短延迟一轮确保 set/Object.keys 同步生效
      setTimeout(() => {
        if (isApiReady()) {
          resolve()
        } else {
          // 还没好，继续轮询
          check()
        }
      }, 0)
    }

    window.addEventListener('pywebviewready', onReady, { once: true })

    // 立即尝试一次（可能已经在 finish.js 之后）
    check()
  })
  return readyPromise
}

export function whenReady(): Promise<void> {
  if (typeof window === 'undefined' || !window.pywebview) {
    return Promise.resolve()
  }
  return buildReadyPromise()
}

// 启动时立即开始等待（避免每次 call 时才初始化）
if (typeof window !== 'undefined' && window.pywebview) {
  buildReadyPromise()
}

async function call<T = any>(name: string, ...args: any[]): Promise<T> {
  await whenReady()
  // 二次兜底：轮询直到目标方法就绪（pywebviewready 后 Object.keys 可能还没更新）
  const start = Date.now()
  const maxWait = 30000  // 30 秒大超时，应对冷启动 + Vite 编译
  while (Date.now() - start < maxWait) {
    const api = window.pywebview?.api
    if (api && typeof api[name] === 'function') {
      try {
        return await api[name](...args)
      } catch (e) {
        // 真正的调用错误（不是"方法不存在"），直接抛
        throw e
      }
    }
    await new Promise((r) => setTimeout(r, 50))
  }
  return Promise.reject(new Error(`[pywebview] 方法不可用：${name}（可能 webview 还未初始化完成）`))
}

/* 应用信息 */
/** 节日主题状态。theme 为空表示今天不是法定假期 */
export interface FestivalTheme {
  ok: boolean
  active: boolean
  theme: string
  name: string
  date?: string
  period?: string
  /** 数据来源：online=联网同步 / cache=本地缓存 / builtin=内置兜底 */
  source?: string
  disabled?: boolean
  error?: string
}

export const appApi = {
  info: () => call<{ version: string; build_date: string }>('get_app_info'),
  disclaimerRequired: () => call<boolean>('get_disclaimer_required'),
  ackDisclaimer: () => call<void>('ack_disclaimer'),
  festivalTheme: () => call<FestivalTheme>('festival_theme'),
}

/* 更新检查 */
export interface UpdateInfo {
  ok: boolean
  has_update: boolean
  current_version?: string
  latest_version?: string
  info?: string
  error?: string
}

export const updateApi = {
  check: () => call<UpdateInfo>('check_update'),
}

/* 配置 */
export const configApi = {
  get: () => call('get_config'),
  update: (updates: Record<string, any>) => call('update_config', updates),
  setCloseBehavior: (b: 'minimize' | 'exit') => call('set_close_behavior', b),
  getCloseBehavior: () => call<string | null>('get_close_behavior'),
}

/* 云端账号（登录注册 + 玩家数据备份） */
export interface AccountStatus {
  ok: boolean
  base_url: string
  timeout: number
  username: string
}

export interface AccountHealth {
  ok: boolean
  reachable: boolean
  service?: string
  version?: string
  users_total?: number
  error?: string
}

export interface AuthResult {
  ok: boolean
  token?: string
  username?: string
  created_at?: string
  has_backup?: boolean
  error?: string
  detail?: string
}

export interface ProfileMod {
  title: string
  url: string
  kind: 'mod' | 'map'
}

export interface BackupStatus {
  ok: boolean
  logged_in: boolean
  mode: 'cloud' | 'local' | 'none'
  auto_enabled: boolean
  preferences_path: string
  preferences_exists: boolean
  backup_mods: number
  installed_mods: number
  installed_maps: number
  last_backup_at: string
}

export interface RestoreResult extends AuthResult {
  preferences_xml?: string
  mods?: ProfileMod[]
  restored?: { preferences: boolean; preferences_path: string }
  mode?: 'cloud' | 'local'
}

export interface BackupResult extends AuthResult {
  updated_at?: string
  mods?: number
  mode?: 'cloud' | 'local'
}

export const backupApi = {
  status: () => call<BackupStatus>('account_backup_status'),
  backupNow: () => call<BackupResult>('account_backup_now'),
  restore: () => call<RestoreResult>('account_restore'),
}

export interface CaptchaResult extends AuthResult {
  captcha_id?: string
  prompt?: string
  image?: string
  expires_in?: number
}

export const authApi = {
  status: () => call<AccountStatus>('get_account_status'),
  setConfig: (cfg: { base_url?: string; timeout?: number }) =>
    call<AccountStatus>('set_account_config', cfg),
  health: () => call<AccountHealth>('account_health'),
  getCaptcha: () => call<CaptchaResult>('account_captcha'),
  register: (username: string, password: string, captchaId: string, captchaAnswer: string, phone = '', email = '') =>
    call<AuthResult>('account_register', username, password, captchaId, captchaAnswer, phone, email),
  login: (username: string, password: string, captchaId: string, captchaAnswer: string) =>
    call<AuthResult>('account_login', username, password, captchaId, captchaAnswer),
  logout: () => call<AuthResult>('account_logout'),
  me: () => call<AuthResult>('account_me'),
  profileUpload: (preferencesXml: string, mods: ProfileMod[]) =>
    call<AuthResult>('account_profile_upload', preferencesXml, mods),
  profilePull: () => call<AuthResult>('account_profile_pull'),
}

/* 游戏 */
export interface GameStatus {
  exists: boolean
  path: string
  game_dir: string
  game_root: string
  /** Java 版（简体中文增强版）入口 jar 是否存在 */
  has_java_jar: boolean
  java_jar: string | null
  /** 是否有可启动目标（exe 或 Java 版 jar） */
  launchable: boolean
  /** 启动分流模式：auto / java / exe */
  mode: 'auto' | 'java' | 'exe'
}

export interface LaunchResult {
  ok: boolean
  pid?: number
  error?: string
  /** 实际采用的启动方式 */
  mode?: 'java' | 'exe'
  /** Java 版启动缺 JRE */
  needs_jre?: boolean
  /** 缺 JRE 且自动下载已在进行 / 已触发 */
  jre_downloading?: boolean
  install_dir?: string
}

export const gameApi = {
  status: () => call<GameStatus>('get_game_status'),
  install: () => call<string>('install_game'),
  launch: (rawArgs: string) => call<LaunchResult>('launch_game', rawArgs),
  /** 快速结束游戏进程；killed=true 表示确实结束了进程 */
  killGame: () => call<{ ok: boolean; killed?: boolean; error?: string; warning?: string }>('kill_game'),
  /** 检测游戏进程是否在运行 */
  gameRunning: () => call<{ running: boolean }>('game_running'),
}

/* Java 版运行环境（JRE） */
export interface JavaRuntimeStatus {
  /** Java 版入口 jar 路径；null 表示只装了原生 exe 版 */
  jar: string | null
  has_jar: boolean
  java_path: string | null
  java_major: number | null
  java_source: 'bundled64' | 'bundled32' | 'system' | 'none'
  needs_install: boolean
  install_dir: string | null
  reason: string
  /** 启动分流配置快照 */
  mode: 'auto' | 'java' | 'exe'
  auto_download: boolean
  feature_version: number
  install_jvm_dir: string
  /** JRE 是否正在后台下载安装 */
  installing: boolean
}

export const javaApi = {
  status: () => call<JavaRuntimeStatus>('java_status'),
  installRuntime: () =>
    call<{ ok: boolean; already?: boolean; installing?: boolean; error?: string }>('install_java_runtime'),
}

/* 版本管理 */
export interface VersionInfo {
  version: string
  build_date?: string
  file_size?: number
  url?: string
  checksum?: string
  description?: string
  is_installed?: boolean
  install_path?: string
  install_date?: string
  edition_name?: string
  file_name?: string
}

export interface EditionInfo {
  name: string
  latest_version: string
  description?: string
  versions: VersionInfo[]
}

export interface VersionOperationResult {
  ok: boolean
  message?: string
  error?: string
  version?: string | null
  install_path?: string
  current_version?: string
  task_id?: string | null
  already_installed?: boolean
  reused?: boolean
  file_size?: number
  description?: string
}

export const versionApi = {
  /** 清单与本地版本（远程失败也返回本地版本及错误） */
  getCatalog: () => call<{ ok: boolean; error?: string; editions: EditionInfo[]; installed_versions: VersionInfo[]; current_version: string | null }>('get_version_catalog'),
  /** 获取编辑版列表 */
  getEditions: () => call<EditionInfo[]>('get_editions'),
  /** 获取远程版本列表 */
  getRemoteVersions: (editionName?: string) => call<VersionInfo[]>('get_remote_versions', editionName),
  /** 获取已安装版本列表 */
  getInstalledVersions: (editionName?: string) => call<VersionInfo[]>('get_installed_versions', editionName),
  /** 检查版本是否已安装 */
  isVersionInstalled: (version: string, editionName?: string) => call<boolean>('is_version_installed', version, editionName),
  /** 下载并安装指定版本（任务化，返回 task_id） */
  installVersion: (version: string, editionName?: string) => call<VersionOperationResult>('install_version', version, editionName ?? null),
  /** 切换到指定版本 */
  switchVersion: (version: string) => call<VersionOperationResult>('switch_version', version),
  /** 启动指定版本（启动成功后该版本自动成为当前版本） */
  launchVersion: (version: string, args = '') =>
    call<LaunchResult & { version?: string }>('launch_version', version, args),
  /** 卸载指定版本 */
  uninstallVersion: (version: string) => call<VersionOperationResult>('uninstall_version', version),
  /** 获取当前版本 */
  getCurrentVersion: () => call<string | null>('get_current_version'),
  /** 获取版本安装路径 */
  getVersionInstallPath: (version: string) => call<string | null>('get_version_install_path', version),
  /** 获取版本详细信息 */
  getVersionDetails: (version: string) => call<VersionInfo | null>('get_version_details', version),
  /** 清除远程版本清单缓存 */
  clearCache: () => call<{ ok: boolean; message?: string }>('clear_version_cache'),
  /** 检查当前配置的版本清单是否可访问（强制重新拉取） */
  checkManifest: () =>
    call<{ ok: boolean; editions?: number; error?: string }>('check_version_manifest'),
}

/* 模组 / 地图 */
export interface ResourceItem {
  title: string
  downurl: string
  img: string
  bbsurl: string
  kind: 'mod' | 'map'
  folder: string
  installed: boolean
  version?: string
  /** 数据源：rtsbox=末忆铁锈盒子 / platform=平台自有（有 mod_id 即平台源） */
  source?: 'rtsbox' | 'platform'
  mod_id?: number
  description?: string
  uploader?: string
  file_size?: number
  downloads?: number
  created_at?: string
}

/** 模组 / 地图搜索结果。error 非空仅代表"这次没有可用结果"，
 *  fallback_reason 代表已降级但结果仍可用（例如账号服务不可用、改走本地 rtsbox 直连）。 */
export interface ResourceSearchResult {
  items: ResourceItem[]
  error: string | null
  /** 实际生效的通道：proxy=配套服务代理 / local=本地 rtsbox 直连 */
  via?: 'proxy' | 'local'
  /** 降级原因。有值时结果依然可用，前端应提示而非报错 */
  fallback_reason?: string | null
}

export const resourceApi = {
  searchMods: (keyword = '', page = 1, pages = 1) =>
    call<ResourceSearchResult>('search_mods', keyword, page, pages),
  searchMaps: (keyword = '', page = 1, pages = 1) =>
    call<ResourceSearchResult>('search_maps', keyword, page, pages),
  getBbsPost: (url: string) =>
    call<{ ok: boolean; html?: string; error?: string }>('get_bbs_post', url),
  listInstalled: (kind: 'mod' | 'map') => call<string[]>('list_installed', kind),
  localInstalled: () =>
    call<{ ok: boolean; items: ProfileMod[]; error?: string }>('resource_local_installed'),
  clearGameCache: (targets: string[]) =>
    call<{ ok: boolean; error: string | null; removed: Record<string, number> }>('clear_game_cache', targets),
  download: (kind: 'mod' | 'map', title: string, downurl: string) =>
    call<{ ok: boolean; task_id?: string; folder?: string; error?: string; installed?: boolean }>(
      'download_resource', kind, title, downurl,
    ),
  cancel: (taskId: string) => call('cancel_download', taskId),
  confirm: (taskId: string, action: 'fix' | 'keep') =>
    call<{ ok: boolean; error?: string }>('confirm_resource', taskId, action),
  list: () => call<Array<{ task_id: string; status: string; downloaded: number; total: number; progress: number; error?: string }>>('get_downloads'),
}

/* 模组分享同步码（配套服务，匿名） */
export interface ShareCodeResult {
  ok: boolean
  code?: string
  mods?: ProfileMod[]
  source?: string
  created_at?: string
  expires_at?: string
  error?: string
}

export const shareCodeApi = {
  create: (mods: ProfileMod[], ttlHours = 0) =>
    call<ShareCodeResult>('share_code_create', mods, ttlHours),
  resolve: (code: string) =>
    call<ShareCodeResult>('share_code_resolve', code),
  delete: (code: string) =>
    call<ShareCodeResult>('share_code_delete', code),
}

/* 房间（配套服务 RW-HPS 集成） */
export interface RoomItem {
  ok?: boolean
  room_id: string
  name: string
  host: string
  players: number
  max_players: number
  version: string
  map: string
  mode: string
  share_code: string
  status: string
  last_seen_at: string
}

export interface RoomListResult {
  ok: boolean
  total: number
  rwhps_configured: boolean
  items: RoomItem[]
  error?: string
}

export interface RoomSyncResult {
  ok: boolean
  queued: number
  total: number
  results?: Array<{ title: string; ok: boolean; error?: string; installed?: boolean }>
  error?: string
}

export const roomApi = {
  list: (status = 'open') => call<RoomListResult>('room_list', status),
  bindShare: (roomId: string, shareCode: string) =>
    call<RoomItem & { error?: string }>('room_bind_share', roomId, shareCode),
  syncMods: (roomId: string) =>
    call<RoomSyncResult>('room_sync_mods', roomId),
}

/* 平台自有 Mod（配套服务，与 rtsbox 并列的数据源 2） */
export interface PlatformModFeedback {
  id: number
  mod_id: number
  username: string
  content: string
  created_at: string
}

export const platformApi = {
  /** 状态页总数据（公网服务探测 + 本机资源 + 事件） */
  status: () =>
    call<{
      ok: boolean
      error?: string
      data?: {
        checked_at?: string
        services?: Array<{
          name: string
          url: string
          status: 'normal' | 'down'
          latency_ms?: number
          uptime_7d?: number
          detail?: string
          /** 后台配置的线路说明：异常时优先展示，无则前端用默认文案 */
          note?: string
        }>
        server?: {
          hostname?: string
          memory_percent?: number | null
          disk_percent?: number | null
          uptime_hours?: number | null
        }
        events?: Array<{
          service: string
          level: string
          detail?: string
          time?: string
        }>
      }
    }>('get_platform_status'),
  /** 搜索平台 Mod / 地图（kind 传 'mod' | 'map' | '' 全部） */
  search: (keyword = '', kind = '', page = 1) =>
    call<{ items: ResourceItem[]; total: number; error: string | null }>(
      'search_platform_mods', keyword, kind, page,
    ),
  /** 下载平台 Mod（.rwmod，复用下载管理器） */
  download: (modId: number, title: string, kind: 'mod' | 'map') =>
    call<{ ok: boolean; task_id?: string; folder?: string; error?: string; installed?: boolean }>(
      'platform_mod_download', modId, title, kind,
    ),
  /** 提交反馈（需登录） */
  feedback: (modId: number, content: string) =>
    call<{ ok: boolean; error?: string; detail?: string }>('platform_mod_feedback', modId, content),
  /** 反馈列表（公开） */
  feedbacks: (modId: number) =>
    call<{ ok: boolean; data?: { total: number; items: PlatformModFeedback[] }; error?: string }>(
      'platform_mod_feedbacks', modId,
    ),
  /** 上传平台 Mod（弹原生文件选择框选 .rwmod，即传即上架，需登录） */
  upload: (title: string, kind: 'mod' | 'map', version: string, description: string) =>
    call<{ ok: boolean; id?: number; error?: string; detail?: string }>(
      'platform_mod_upload', title, kind, version, description,
    ),
}

/* 窗口控制 */
export const windowApi = {
 minimize: () => call('minimize_window'),
  close: () => call('close_window'),
  /**
   * 切换窗口最大化 / 还原（无返回，状态通过 rw:window:maxstate 事件推送）。
   */
  toggleMaximize: () => call('toggle_maximize'),
  /** 查询窗口当前状态（标题栏初始化用）。 */
  getWindowState: () => call<{ maximized: boolean }>('get_window_state'),
  openUrl: (url: string) => call<boolean>('open_url', url),
  /**
   * 选择一张图片作为启动器背景（复制到启动器目录 backgrounds/ 后返回）。
   * 取消时返回 { ok: false, canceled: true }。
   * data_uri 为 base64 内嵌图，可直接用于 CSS 背景。
   */
  pickBackgroundImage: () =>
    call<{ ok: boolean; path?: string; data_uri?: string; canceled?: boolean; error?: string }>(
      'pick_background_image',
    ),
  /**
   * 返回当前背景图的 base64 data URI；未设置时 data 为空串。
   */
  backgroundImageData: () => call<{ ok: boolean; data?: string }>('background_image_data'),
  /**
   * 通知宿主窗口开始"标题栏拖动"。
   * 用于替代 CSS `-webkit-app-region: drag`（WebView2 不响应此 CSS）。
   * 一般在 TitleBar 的 mousedown 事件里调用（仅左键）。
   */
  beginWindowDrag: () => call<boolean>('begin_window_drag'),
}

/* 手动诊断（自动告警机制已移除，仅保留用户主动运行的全项诊断） */
export interface DiagnoseItem {
  id: string
  label: string
  status: 'ok' | 'warn' | 'error' | 'info'
  message: string
}

export interface DiagnoseReport {
  checked_at: string
  items: DiagnoseItem[]
  summary: string
}

export const diagnoseApi = {
  /** 手动运行一次全项诊断 */
  run: () => call<DiagnoseReport>('run_diagnosis'),
}

/* FRP 内网穿透 */
export interface FrpConfigData {
  enabled: boolean
  server_addr: string
  server_port: number
  auth_token: string
  proxy_name: string
  proxy_type: 'tcp' | 'udp'
  local_ip: string
  local_port: number
  frpc_path: string
}

export interface FrpStatusData {
  installed: boolean
  frpc_path: string
  running: boolean
  pid: number
  config_path: string
  last_error: string
  last_log_lines: string[]
}

export const frpApi = {
  /** 读取 frp 配置 */
  getConfig: () => call<{ ok: boolean; config: FrpConfigData }>('get_frp_config'),
  /** 更新 frp 配置（不立即启动） */
  setConfig: (updates: Partial<FrpConfigData>) =>
    call<{ ok: boolean; error?: string; config?: FrpConfigData }>('set_frp_config', updates),
  /** 启动 frpc 子进程 */
  start: () =>
    call<{ ok: boolean; pid?: number; error?: string; already_running?: boolean }>('start_frp'),
  /** 停止 frpc 子进程 */
  stop: () =>
    call<{ ok: boolean; error?: string; already_stopped?: boolean }>('stop_frp'),
  /** 查询 frp 状态 */
  status: () => call<{ ok: boolean; status: FrpStatusData }>('get_frp_status'),
}

/* 存档管理 */
export interface SaveItem {
  name: string
  relpath: string
  path: string
  size: number
  mtime: number
  location: string
}

export interface SaveBackup {
  name: string
  path: string
  count: number
  size: number
  created: string
}

export const saveApi = {
  /** 列出全部存档（便携版与我的文档版） */
  list: () => call<{ dirs: string[]; items: SaveItem[] }>('list_saves'),
  /** 备份指定存档（paths 为空时备份全部） */
  backup: (paths?: string[]) =>
    call<{ ok: boolean; error?: string; created?: string; count?: number; path?: string }>(
      'backup_saves', paths,
    ),
  /** 列出全部存档备份 */
  backups: () => call<{ items: SaveBackup[] }>('list_save_backups'),
  /** 从备份恢复到原位置 */
  restore: (name: string) =>
    call<{ ok: boolean; error?: string; restored?: number }>('restore_save_backup', name),
  /** 删除存档 */
  delete: (paths: string[]) =>
    call<{ ok: boolean; error?: string; removed?: number }>('delete_saves', paths),
  /** 删除一个存档备份 */
  deleteBackup: (name: string) => call<{ ok: boolean; error?: string }>('delete_save_backup', name),
  /** 打开存档目录 */
  openDir: () => call<{ ok: boolean; error?: string; path?: string }>('open_saves_dir'),
}
