/**
 * 单条状态连接，掉线 1.5 秒后重连；只把 `type` 匹配的消息交给 onMessage。
 * watchdog 开启时：服务端空闲每 15 秒发 ping，25 秒（刚连接时 10 秒）收不到任何消息就主动重连。
 */
export function subscribeSocket<T>(
  path: string,
  type: string,
  onMessage: (message: T) => void,
  onConnection: (open: boolean) => void,
  watchdog = true,
): () => void {
  let socket: WebSocket | undefined
  let retry = 0
  let timer = 0
  let stopped = false

  function armWatchdog(timeout = 25000) {
    if (!watchdog) return
    clearTimeout(timer)
    timer = window.setTimeout(() => socket?.close(), timeout)
  }

  function open() {
    if (stopped) return
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocket(`${protocol}//${location.host}${path}`)
    armWatchdog(10000)
    socket.onopen = () => { onConnection(true); armWatchdog() }
    socket.onmessage = (event) => {
      armWatchdog()
      try {
        const message = JSON.parse(event.data)
        if (message.type === type) onMessage(message as T)
      } catch {
        socket?.close()
      }
    }
    socket.onerror = () => socket?.close()
    socket.onclose = () => {
      clearTimeout(timer)
      onConnection(false)
      if (!stopped) retry = window.setTimeout(open, 1500)
    }
  }

  open()
  return () => {
    stopped = true
    clearTimeout(retry)
    clearTimeout(timer)
    socket?.close()
  }
}
