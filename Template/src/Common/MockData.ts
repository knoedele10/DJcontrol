// 模拟数据：后端完成前，前端用这些数据开发和演示。
import type { EventGroup, KugouResult, PptSlide, Song } from '@/Common/Types'

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

const KUGOU_ROWS: Row[] = [
  ['七里香', '周杰伦', 90, 299], ['告白气球', '周杰伦', 92, 215], ['青花瓷', '周杰伦', 68, 239],
  ['夜曲', '周杰伦', 84, 226], ['本草纲目', '周杰伦', 96, 208], ['晴天 (Live)', '周杰伦', 69, 281],
  ['十年', '陈奕迅', 76, 205], ['富士山下', '陈奕迅', 72, 259], ['浮夸', '陈奕迅', 88, 284],
  ['孤勇者 (伴奏)', '陈奕迅', 140, 256], ['突然好想你', '五月天', 78, 265], ['知足', '五月天', 72, 262],
  ['倔强', '五月天', 132, 260], ['演员', '薛之谦', 72, 261], ['泡沫', '邓紫棋', 75, 258],
  ['光辉岁月', 'Beyond', 80, 301], ['真的爱你', 'Beyond', 78, 275], ['年少有为', '李荣浩', 70, 280],
  ['漠河舞厅', '柳爽', 72, 302], ['大鱼', '周深', 66, 313], ['怒放的生命', '汪峰', 140, 276],
  ['春天里', '汪峰', 78, 293], ['江南', '林俊杰', 74, 267], ['曹操', '林俊杰', 96, 242],
  ['隐形的翅膀', '张韶涵', 70, 227], ['勇气', '梁静茹', 70, 240], ['阳光总在风雨后', '许美静', 72, 262],
  ['我们都是追梦人', '群星', 100, 231], ['运动员进行曲 (高清版)', '军乐团', 120, 152], ['少年', '梦然', 86, 238],
]

export const mockKugouCatalog: KugouResult[] = KUGOU_ROWS.map(([title, artist, bpm, duration], i) => ({
  key: `kg-${i}`, title, artist, bpm, duration,
}))

export const seedPptSlides = (): PptSlide[] => [
  { title: '2026 秋季运动会', subtitle: '开幕式', bg: '#3b1d8f', songId: null },
  { title: '运动员入场', subtitle: '各班依次入场', bg: '#0b7a5c', songId: 18 },
  { title: '领导致辞', subtitle: '', bg: '#3a3566', songId: null },
  { title: '比赛项目', subtitle: '100 米 · 跳远 · 4×100 接力', bg: '#b8401a', songId: 20 },
  { title: '颁奖：男子 100 米', subtitle: '第一名 · 第二名 · 第三名', bg: '#a8770a', songId: 25 },
  { title: '中场休息', subtitle: '15 分钟后继续', bg: '#0d6f86', songId: null },
  { title: '颁奖：团体总分', subtitle: '', bg: '#a8770a', songId: 25 },
  { title: '闭幕', subtitle: '感谢参与', bg: '#3b1d8f', songId: 6 },
]

export const PALETTE = ['#00e0a4', '#ff6a2b', '#a66bff', '#ff3da6', '#ffc928', '#2fb8ff', '#3df0e0', '#d36bff']
