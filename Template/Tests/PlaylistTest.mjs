import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { createServer } from 'vite'
import { createPinia, setActivePinia } from 'pinia'

let vite, usePlaybackStore, useQueueStore
const snapshot = (songs = {}) => ({ name: '演出歌单', route: 'A', supported: true, can_add: true, complete: true, note: '测试探测', songs })
const response = (payload, ok = true) => ({ ok, json: async () => payload })

before(async () => {
  globalThis.window = globalThis
  globalThis.location = { protocol: 'http:', host: 'localhost:5173' }
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ usePlaybackStore } = await vite.ssrLoadModule('/src/Playback/PlaybackStore.ts'))
  ;({ useQueueStore } = await vite.ssrLoadModule('/src/Queue/QueueStore.ts'))
})
beforeEach(() => setActivePinia(createPinia()))
after(async () => { await vite?.close() })

test('unverified addition displays a failure and does not claim membership or consume queue items', async () => {
  const playback = usePlaybackStore()
  const queue = useQueueStore()
  queue.applyRemoteState({ queue: [{ id: 'q1', song_id: 1, added_at: 'now' }], recent_history: [], session: null })
  let submitted
  globalThis.fetch = async (url, init) => {
    submitted = { url, body: JSON.parse(init.body) }
    return response({ status: 'unverified', message: '没有核验到添加结果', in_playlist: null, playlist: snapshot({ 1: null }) })
  }
  await playback.addPlaylistSong(1)
  assert.deepEqual(submitted, { url: '/api/playlist/tracks', body: { song_id: 1 } })
  assert.equal(playback.command.status, 'failed')
  assert.match(playback.command.text, /没有核验/)
  assert.equal(playback.playlist.songs['1'], null)
  assert.equal(queue.positionOf(1), 0)
})

test('in-flight addition blocks duplicate additions and ordinary play commands', async () => {
  const playback = usePlaybackStore()
  let finish, requests = 0
  globalThis.fetch = () => {
    requests++
    return new Promise(resolve => { finish = resolve })
  }
  const pending = playback.addPlaylistSong(1)
  assert.equal(playback.busy, true)
  await playback.addPlaylistSong(1)
  await playback.play(1)
  assert.equal(requests, 1)
  finish(response({ status: 'added', message: '已加入并核验', in_playlist: true, playlist: snapshot({ 1: true }) }))
  await pending
  assert.equal(playback.busy, false)
  assert.equal(playback.command.status, 'verified')
  assert.equal(playback.playlist.songs['1'], true)
})

test('request validation errors remain readable and release the busy state', async () => {
  const playback = usePlaybackStore()
  globalThis.fetch = async () => response({ detail: [{ msg: '歌曲编号无效' }] }, false)
  await playback.addPlaylistSong(1)
  assert.equal(playback.busy, false)
  assert.equal(playback.command.status, 'failed')
  assert.equal(playback.command.text, '歌曲编号无效')
})

test('playback logs the verified route returned by the backend', async () => {
  const playback = usePlaybackStore()
  globalThis.fetch = async url => response(url === '/api/playlist' ? snapshot({ 1: true }) : {
    type: 'player_state', revision: 1,
    state: { controller: 'kugou', connected: true, song_id: 1, title: '晴天', artist: '周杰伦', status: 'playing',
      position: 0, duration: 269, queue: [], recent_history: [], session: null, auto_next: false,
      error: null, capabilities: [], via: 'playlist' },
  })
  await playback.play(1)
  assert.equal(playback.command.status, 'verified')
  assert.match(playback.command.text, /歌单直播放/)
})

test('failed membership refresh clears stale badges', async () => {
  const playback = usePlaybackStore()
  playback.playlist = snapshot({ 1: true })
  globalThis.fetch = async () => { throw new Error('服务中断') }
  await playback.loadPlaylist()
  assert.equal(playback.playlist, null)
})

test('an older membership response cannot overwrite a newer saved configuration', async () => {
  const playback = usePlaybackStore()
  let finish
  globalThis.fetch = () => new Promise(resolve => { finish = resolve })
  const pending = playback.loadPlaylist()
  playback.applyPlaylist({ ...snapshot(), name: '另一歌单' })
  finish(response(snapshot({ 1: true })))
  await pending
  assert.equal(playback.playlist.name, '另一歌单')
  assert.deepEqual(playback.playlist.songs, {})
})
