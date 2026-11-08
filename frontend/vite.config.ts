import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// Vite 配置
// 关键点：base 必须为 './'，否则构建后的资源路径在 file:// 下加载不到
export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需加载：自动引入组件、对应样式 + API
    AutoImport({
      resolvers: [ElementPlusResolver()],
      // 自动引入的 API 类型声明
      dts: 'src/auto-imports.d.ts',
      // 避免在每个文件里重复 import
      imports: ['vue'],
    }),
    Components({
      resolvers: [
        ElementPlusResolver({
          // 导入样式的同时导入对应的 scss 变量，避免丢失自定义覆盖
          importStyle: 'sass',
        }),
      ],
      dts: 'src/components.d.ts',
      // 自动将 template 中用到的组件注册为全局
      directoryAsNamespace: false,
    }),
  ],
  // 构建时刻注入：设置页/关于页据此核对版本，构建一次更新一次
  define: {
    __BUILD_DATE__: JSON.stringify(
      new Date().toLocaleString('zh-CN', { hour12: false }),
    ),
  },
  base: './',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
  },
  css: {
    preprocessorOptions: {
      scss: {
        // 注入 Element Plus 变量覆盖（空白覆盖，保留默认值，依靠 element-overrides.css 做黑白覆写）
        additionalData: '',
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2020',
    // 减小行内资源体积阈值，让大图单独输出
    assetsInlineLimit: 4096,
    // 提升警告阈值，避免被 Element Plus 的 chunk 大小吓到
    chunkSizeWarningLimit: 2000,
    // 按组件拆 CSS，避免单个大 CSS 文件
    cssCodeSplit: true,
    // 生产构建时删除所有 console / debugger
    minify: 'esbuild',
    // terserOptions: { compress: { drop_console: true, drop_debugger: true } },
    rollupOptions: {
      output: {
        // 智能分包：不写死 manualChunks，
        // Element Plus 已经由 unplugin 按需导入，
        // 让 Vite 自己决策 chunk 边界
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
})
