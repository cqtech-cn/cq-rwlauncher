# LEProc.exe 放置说明

## 这是什么

Locale Emulator（LE）是一个轻量级转区工具，能在不修改系统区域设置的前提下，
**对单个进程注入指定语言的 locale**。用它启动《铁锈战争》，
可以让 libGDX 后端正确处理中文 IME 输入，解决游戏内输不了中文的问题。

## 文件

本目录需要放一个文件：**`LEProc.exe`**（Locale Emulator 的命令行启动器，~29KB）

启动器启动游戏时，若配置项 `locale_emulator.enabled = true`，
会用以下命令包装游戏 exe：

```
LEProc.exe -runas <LCID> "<game_exe>" <args>
```

例如：LEProc.exe -runas 2052 "RustedWarfare.exe" -host

## 怎么获取 LEProc.exe

**官方源（推荐）：** https://github.com/xupefei/Locale-Emulator/releases
- 下载 `LEPack.zip`（2.5.0.1 版本约 195KB）
- 解压后从 `LEPack\` 子目录取出 `LEProc.exe`
- 把 `LEProc.exe` 放到本目录（与本 README 同级）

**国内镜像（如 GitHub 难访问）：**
- 码云镜像: https://gitee.com/mirrors/Locale-Emulator （如有）
- 百度网盘秒传代码（2.5.0.1 zip）: `6e1a6cb34e33966befef0ae119c532b8#154135#/Locale.Emulator.2.5.0.1.zip`

**国内下载站（CSDN 等）搜索 "Locale Emulator 2.5.0.1"** 也可获取，
解压后取其中的 `LEProc.exe`。

## 需要的运行时

LEProc 依赖（已包含在 Windows 10/11 内）：
- .NET Framework 4.5+（Win10+ 自带）
- MSVC++ Runtime（Win10+ 自带）

## 验证放置正确

放好 LEProc.exe 后，启动启动器 → 设置 → 找到 Locale Emulator 配置区，
**LEProc 状态** 应显示 "已就绪"（自动检测本目录 LEProc.exe 是否存在）。

## 在哪里配置

启动器 → 设置页 → 找到 "Locale Emulator" 分组：
- **启用 LEProc 启动游戏**：开启 / 关闭
- **目标 locale**：
  - `2052` = 简体中文（中国大陆）
  - `1041` = 日语
  - `1033` = 英语（美国）
  - `1028` = 繁体中文
- **LEProc 路径**：留空自动用本目录的 `LEProc.exe`；
  填绝对路径则用指定的（适用于系统已安装 LE 的情况）

## 安全说明

- LEProc 来自官方/镜像，**不需要以管理员身份运行**
- LEProc.exe **不修改游戏**（不注入 DLL 到游戏进程），只在启动时
  通过 CreateProcess hook 注入 transient locale context
- 退出游戏后 LEProc 自动退出，对系统零残留

## 卸载

删除 `LEProc.exe` 即可，无任何注册表 / 系统文件残留。
