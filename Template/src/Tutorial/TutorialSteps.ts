// 使用教程的每一步。targets 按顺序找第一个在页面上可见的元素来高亮，都找不到就把卡片居中。
// 文字里用 [键名] 标出按键，界面会显示成键帽样式。

export interface TutorialStep {
  id: string
  title: string
  lines: string[]
  targets?: string[]
}

export const TUTORIAL_STEPS: TutorialStep[] = [
  {
    id: 'welcome',
    title: '欢迎使用酷狗统筹面板',
    lines: [
      '选歌、排队、控制酷狗播放和 PPT 翻页，都在这一个屏幕上完成。',
      '下面带你认识每个区域，大约 1 分钟；可以用 [←] [→] 键翻页。',
    ],
  },
  {
    id: 'status',
    title: '顶部状态栏',
    targets: ['[data-tour="status"]'],
    lines: [
      '显示正在播放的歌、播放进度和播放器连接状态；点进度条可以跳转。',
      '绿色「● 已连接 · 酷狗」表示正在控制酷狗；黄色「模拟播放器」表示还没切到酷狗，播放只是演示、不会出声。',
    ],
  },
  {
    id: 'settings',
    title: '设置与连接诊断',
    targets: ['[data-tour="settings"]'],
    lines: [
      '正式使用前先来这里：把「控制方式」切到「酷狗音乐」，填好「演出歌单」名称，再看「能力自检」里哪些功能可用。',
      '酷狗主窗口要一直开着，不能最小化或收进托盘。',
    ],
  },
  {
    id: 'groups',
    title: '活动分组',
    targets: ['[data-tour="groups"]', '[data-tour="sidebar"]'],
    lines: [
      '每场活动建一个组，比如「运动会」「毕业晚会」，点组名切换。',
      '鼠标移到组名上可以重命名或删除，删除要再点一次「确认删除」。',
    ],
  },
  {
    id: 'categories',
    title: '分类',
    targets: ['[data-tour="categories"]', '[data-tour="sidebar"]'],
    lines: [
      '组里按环节分类，比如入场、颁奖、中场休息；按数字键 [1]–[9] 快速切换。',
      '把歌曲卡片拖到分类上就能加进去；选中分类后点「管理本分类歌曲」可以批量增删。',
    ],
  },
  {
    id: 'search',
    title: '搜歌',
    targets: ['[data-tour="search"]'],
    lines: [
      '输入歌名或歌手，同时搜曲库和酷狗；按 [/] 直接跳到搜索框。',
      '[回车] 把第一首加入队列，[Shift]+[回车] 立即播放。不在曲库的酷狗结果也能直接播、排队或收进曲库。',
    ],
  },
  {
    id: 'song-card',
    title: '歌曲卡片',
    targets: ['[data-song-card]', '[data-tour="browser"]'],
    lines: [
      '单击卡片加入待播队列；拖到左侧分类就加入该分类。',
      '右上角按钮：⤒ 插到下一首，▶ 立即播放，⌗ 设置分组。',
      '酷狗模式下还有「♫＋」，把歌加进演出歌单；它会试听切歌，请在演出前做。',
    ],
  },
  {
    id: 'queue',
    title: '待播队列',
    targets: ['[data-tour="queue"]'],
    lines: [
      '排第一的就是「下一首」。每行的 ← → 调整顺序，✕ 移除；右上角 ✕ 清空队列。',
      '按 [N] 或「▶ 播下一首」播放它；播过的歌会记在左下角「本场已播」。',
    ],
  },
  {
    id: 'transport',
    title: '播放控制',
    targets: ['[data-tour="transport"]'],
    lines: [
      '中间大按钮播放 / 暂停（[空格]），⏮ 上一首，「⏭ 播队列下一首」（[N]）；酷狗模式下的「⏭ 酷狗下一首」切的是酷狗自己的列表。',
      '「快结束时自动接歌」只在模拟播放器下可用，用酷狗时请手动播下一首。',
      '鼠标移到「⌨ 快捷键」可查看全部快捷键；最右边显示最近一条命令是否已核验成功。',
    ],
  },
  {
    id: 'ppt',
    title: 'PPT 放映',
    targets: ['[data-tour="ppt"]'],
    lines: [
      '先在 PowerPoint 或 WPS 里打开文稿，再在这里选对软件；连不上就点「重新连接」。',
      '[←] [→]、[PgUp] [PgDn] 或翻页笔翻页，[B] 黑屏，[P] 放大这一栏。',
      '播放一首歌后点「绑定」，这首歌就绑到当前页；勾选「翻页联动音乐」，翻到这页会自动播放它。',
    ],
  },
  {
    id: 'done',
    title: '准备好了',
    targets: ['[data-tour="help"]'],
    lines: [
      '演出前检查：① 设置里切到「酷狗音乐」并重新检测；② 酷狗主窗口保持打开；③ 在演示软件里打开 PPT 并连接。',
      '以后随时点这里的「？ 教程」重新查看。',
    ],
  },
]
