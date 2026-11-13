// 模拟数据：后端完成前，前端用这些数据开发和演示。
import type { EventGroup, Song } from '@/Common/Types'

type Row = [title: string, artist: string, bpm: number, duration: number]

const LIBRARY_ROWS: Row[] = [
  ['夜空中最亮的星', '逃跑计划', 96, 252], ['晴天', '周杰伦', 69, 269], ['平凡之路', '朴树', 85, 301],
  ['稻香', '周杰伦', 82, 223], ['光年之外', '邓紫棋', 78, 235], ['孤勇者', '陈奕迅', 140, 256],
  ['海阔天空', 'Beyond', 148, 326], ['倔强', '五月天', 132, 260], ['离开地球表面', '五月天', 150, 251],
  ['Unstoppable', 'Sia', 174, 217], ['起风了', '买辣椒也用券', 80, 325], ['小幸运', '田馥甄', 82, 265],
  ['后来', '刘若英', 76, 341], ['红豆', '王菲', 72, 253], ['野狼disco', '宝石Gem', 128, 249],
  ['最炫民族风', '凤凰传奇', 130, 287], ['恭喜发财', '刘德华', 120, 210], ['学猫叫', '小潘潘', 120, 214],
  ['运动员进行曲', '军乐团', 120, 150], ['拉德茨基进行曲', '维也纳爱乐', 112, 180], ['We Will Rock You', 'Queen', 81, 122],
  ['我相信', '杨培安', 136, 268], ['超越梦想', '汪正正', 90, 270], ['奔跑', '羽泉', 145, 263],
  ['相亲相爱', '群星', 90, 284], ['We Are the Champions', 'Queen', 64, 179], ['追梦赤子心', 'GALA', 150, 302],
  ['Hall of Fame', 'The Script', 85, 202],
]

export const seedSongs = (): Song[] =>
  LIBRARY_ROWS.map(([title, artist, bpm, duration], id) => ({ id, title, artist, bpm, duration, source: 'library', note: '' }))

export const seedGroups = (): EventGroup[] => [
  {
    id: 'g1', name: '演唱会', color: '#ff3da6',
    categories: [
      { id: 'c1', name: '暖场', color: '#00e0a4', song_ids: [0, 1, 2, 3, 4] },
      { id: 'c2', name: '高潮', color: '#ff6a2b', song_ids: [5, 6, 7, 8, 9] },
      { id: 'c3', name: '慢歌', color: '#a66bff', song_ids: [10, 11, 12, 13] },
      { id: 'c4', name: '互动', color: '#ffc928', song_ids: [14, 15, 16, 17] },
    ],
  },
  {
    id: 'g2', name: '运动会', color: '#2fb8ff',
    categories: [
      { id: 'c5', name: '入场式', color: '#2fb8ff', song_ids: [18, 19, 26] },
      { id: 'c6', name: '比赛进行中', color: '#ff6a2b', song_ids: [20, 21, 23, 9, 27] },
      { id: 'c7', name: '颁奖', color: '#ffc928', song_ids: [25, 22, 6] },
      { id: 'c8', name: '中场休息', color: '#00e0a4', song_ids: [24, 14, 15, 3] },
    ],
  },
]

export const PALETTE = ['#00e0a4', '#ff6a2b', '#a66bff', '#ff3da6', '#ffc928', '#2fb8ff', '#3df0e0', '#d36bff']
