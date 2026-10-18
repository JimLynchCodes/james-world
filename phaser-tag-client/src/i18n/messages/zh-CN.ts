import type { Messages } from "./en-US.ts";

/** Simplified Chinese, mainland. 鬼 is the kid who is "it". */
export const zhCN: Messages = {
  "meta.title": "捉人游戏",

  "title.kicker": "欢迎来到",
  "title.heading": "詹姆斯世界",
  "title.blurb": "到处跑、玩捉人，好好开心！",
  "title.start": "开始",
  "title.starting": "正在开始…",

  "hud.connecting": "正在连接…",
  "hud.connected": "已连接",
  "hud.notConnected": "未连接",
  "hud.playersLabel": "玩家：",
  "hud.players.one": "{count} 位玩家",
  "hud.players.other": "{count} 位玩家",
  "hud.energy": "能量",

  "toast.connectionLost": "连接中断，正在重连…",
  "toast.reconnected": "已作为 {name} 重新连接",
  "toast.joinedSelf": "你以 {name} 的身份加入了",
  "toast.joined": "{name} 加入了",
  "toast.left": "{name} 离开了",
  "toast.leftUnknown": "有玩家离开了",
  "toast.serverError": "服务器错误：{message}",

  "label.you": "你",
  "label.it": "鬼",

  "hint.keyboard":
    "<strong>WASD / 方向键</strong>移动 · <strong>SHIFT</strong>奔跑 · <strong>空格</strong>或 <strong>T</strong>抓人",
  "hint.mobile":
    "<strong>点</strong>地面走路，或用<strong>摇杆</strong> · <strong>抓</strong>一下，或点身边的玩家 · 按住<strong>跑</strong>就能冲",
  "hint.mobileTouch":
    "<strong>点</strong>地面走路 · <strong>双击</strong>奔跑 · <strong>点玩家</strong>抓人",
  "hint.dismiss": "关闭提示",

  "settings.aria": "设置",
  "settings.title": "设置",
  "settings.close": "关闭设置",
  "settings.tab.controls": "操作",
  "settings.tab.sound": "声音",
  "settings.tab.view": "视角",
  "settings.tab.skins": "皮肤",
  "settings.tab.credits": "制作",

  "settings.controls.heading": "操作",
  "settings.controls.moveWith": "移动方式",
  "settings.controls.keyboard": "键盘",
  "settings.controls.mobile": "触屏",
  "settings.controls.flipJoystick": "摇杆换边",
  "settings.controls.flipTagRun": "抓人 / 奔跑对调",
  "settings.controls.off": "关",
  "settings.controls.on": "开",
  "settings.controls.hideButtons": "隐藏按钮",
  "settings.controls.phoneHint":
    "用手机或平板？选<strong>触屏</strong>就能用摇杆，还有大号的抓人和奔跑按钮。",

  "howto.aria": "怎么玩",
  "howto.title": "怎么玩",
  "howto.move": "移动",
  "howto.or": "或",
  "howto.runHold": "奔跑（按住）",
  "howto.tag": "抓人！",
  "howto.shift": "Shift",
  "howto.space": "空格",
  "howto.up": "上方向键",
  "howto.down": "下方向键",
  "howto.left": "左方向键",
  "howto.right": "右方向键",
  "howto.joyWalk": "摇杆，或点地面，用来走",
  "howto.tagTap": "抓人，或点一下身边的玩家",
  "howto.holdRun": "按住就能跑",
  "howto.zoomIn": "拉近",
  "howto.zoomOut": "拉远",
  "howto.pinch": "双指捏合缩放",
  "howto.tapWalk": "点地面走路",
  "howto.doubleRun": "双击地面奔跑",
  "howto.tapPlayer": "点玩家抓人",
  "howto.helpMobile": "在地面上拖动就能转向。随便搭配！适合手机和平板。",
  "howto.helpTouch": "够不着的话，会走过去。",
  "howto.helpKeyboard": "拍一下身边的人，让对方当鬼。",

  "settings.sound.heading": "声音",
  "settings.sound.master": "主音量",
  "settings.sound.music": "背景音乐",
  "settings.sound.sfx": "音效",
  "settings.sound.mood": "氛围",
  "settings.sound.moodHelp": "氛围决定背景音乐。",

  "settings.view.heading": "视角",
  "settings.view.zoom": "缩放",
  "settings.view.out": "拉远",
  "settings.view.in": "拉近",
  "settings.view.help": "中间（0）是正常缩放。拉远能看到更多地图，拉近看得更清楚。",
  "settings.view.input": "Alt + ↑ 或 W 拉近。Alt + ↓ 或 S 拉远。双指捏合缩放。",

  "mood.happy": "欢快",
  "mood.happy.blurb": "蹦跳的芯片音乐",
  "mood.spooky": "阴森",
  "mood.spooky.blurb": "诡异的钟声和心跳",
  "mood.relaxed": "轻松",
  "mood.relaxed.blurb": "松弛的 lo-fi 键盘",
  "mood.chillin": "悠闲",
  "mood.chillin.blurb": "Lo-fi 嘻哈循环",

  "settings.skins.heading": "皮肤",
  "settings.skins.help": "还是这个主角，换一身行头。",
  "settings.skins.aria": "皮肤",

  "skin.james": "詹姆斯",
  "skin.james.note": "普通詹姆斯",
  "skin.banana": "香蕉詹姆斯",
  "skin.banana.note": "舔一口就跑！",
  "skin.trex": "恐龙詹姆斯",
  "skin.trex.note": "霸王龙抓人！",
  "skin.tuxedo": "燕尾服詹姆斯",
  "skin.tuxedo.note": "盛装出席！",
  "skin.pirate": "海盗詹姆斯",
  "skin.pirate.note": "啊哈，你是鬼！",
  "skin.pharaoh": "法老詹姆斯",
  "skin.pharaoh.note": "走路像埃及人！",

  "settings.credits.heading": "制作",
  "credits.bio":
    "这款游戏由 James 制作。他是住在纽约的软件工程师（大家也叫他 Jim、Jimbo、Jimothy 和 Sir Jims-a-lot）。",
  "credits.linkedinLead": "欢迎在 LinkedIn 上与我联系：",
  "credits.githubLead": "来看看这款游戏的源代码，Fork 一下，再点个星吧！ 😉",
  "credits.newTab": "在新标签页中打开。",
  "credits.photoAlt": "James",

  "mobile.tag": "抓",
  "mobile.tagAria": "抓人",
  "mobile.run": "跑",
  "mobile.runAria": "奔跑（按住）",
  "mobile.joystickAria": "摇杆：拖动即可移动",

  "lang.choose": "选择语言",

  "cave.line1": "把当鬼练到家，",
  "cave.line2": "这东西就归你。",

  "bsod.aria": "错误：任务尚未实现。",
  "bsod.text": `检测到问题，James World 已关闭，以免损坏
你的计算机。

错误：任务尚未实现。

如果这是你第一次看到这个停止错误屏幕，
请重新启动计算机。如果此屏幕再次出现，请按
以下步骤操作：

请确认任何新的硬件或软件均已正确安装。
如果这是新安装，请向硬件或软件制造商
索取你可能需要的 James World 更新。

如果问题仍然存在，请禁用或删除任何新安装的硬件
或软件。请禁用 BIOS 内存选项，例如缓存或影子内存。
如果需要使用安全模式来删除或禁用组件，请重新启动
计算机，按 F8 选择高级启动选项，然后
选择安全模式。

技术信息：

*** STOP: 0x0000007B (0xC0000034, 0x00000000, 0x00000000, 0x00000000)


按任意键或点按以继续 `,
};
