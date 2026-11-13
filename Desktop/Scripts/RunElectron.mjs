import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const electronBinary = require('electron')
const desktopRoot = path.resolve(import.meta.dirname, '..')

// IDE 终端可能注入 ELECTRON_RUN_AS_NODE=1，直接运行 electron 会退化成纯 Node 进程。
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const child = spawn(electronBinary, [desktopRoot, ...process.argv.slice(2)], {
  cwd: desktopRoot,
  env,
  stdio: 'inherit',
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 0)
})
