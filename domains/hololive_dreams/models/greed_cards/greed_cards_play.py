"""Local High&Low perception and verified execution. No navigation or cloud calls.
Rules: user-confirmed 2026-10-02; independent implementation, not vendored bot code.
"""
import json
import re
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from modular_agent.core import Action, Outcome
from modular_agent.perception.report import Rect

VERSION = '0.4.8'
TEMPLATE_THRESHOLD = 0.5
SPATIAL_MATCH_GAP = 0.15
RANKS = tuple(map(str, range(2, 11))) + ('j', 'q', 'k', 'a')
SUITS = ('spade', 'heart', 'diamond', 'club')
TEMPLATE_NAMES = tuple('hl_rank_' + r for r in RANKS) + tuple('hl_suit_' + s for s in SUITS) + ('hl_joker',)


def norm(value):
    return ''.join(str(value).split()).lower().replace('＆', '&')


def window_at_point(x,y):
    """Read-only Win32 hit test; resolves child handles to their root window."""
    import ctypes
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.WindowFromPoint.argtypes=[wintypes.POINT]
    user.WindowFromPoint.restype=wintypes.HWND
    user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
    user.GetAncestor.restype=wintypes.HWND
    handle=user.WindowFromPoint(wintypes.POINT(int(x),int(y)))
    return int(user.GetAncestor(handle,2) or handle or 0)


def occluding_windows(windows, game, hit_test=None):
    """Rectangles find candidates; real Win32 windows require hit-test evidence.

    Synthetic/non-Win32 reports keep the geometric fallback for offline tests.
    An injected hit test permits deterministic transparent-window regression tests.
    """
    bounds=Rect.from_bbox(game['bounds']['bbox'])
    candidates=[w for w in windows if w.get('handle') != game.get('handle')
            and not w.get('minimized') and 'bounds' in w
            and w.get('z_order',99999) < game.get('z_order',0)
            and Rect.from_bbox(w['bounds']['bbox']).intersection(bounds).area]
    if hit_test is None and game.get('source')!='win32': return candidates
    probe=hit_test or window_at_point
    confirmed=[]
    for window in candidates:
        overlap=Rect.from_bbox(window['bounds']['bbox']).intersection(bounds)
        hits=[]
        for fy in (.1,.3,.5,.7,.9):
            for fx in (.1,.3,.5,.7,.9):
                x=min(overlap.x+overlap.width-1,round(overlap.x+fx*overlap.width))
                y=min(overlap.y+overlap.height-1,round(overlap.y+fy*overlap.height))
                root=probe(x,y)
                if root==window['handle']: hits.append({'x':x,'y':y})
        if hits:
            confirmed.append({**window,'occlusion_evidence':{'method':'WindowFromPoint','points':hits}})
    return confirmed


def classify(report):
    if report.frame.get('high_low_template_state'):
        return report.frame['high_low_template_state']
    words = [norm(t.get('text', '')) for t in report.texts]
    has = lambda s: any(norm(s) in w for w in words)
    if has('今日') and (has('上限') or has('限额')):
        return 'daily_limit'
    if has('要再玩一次扑克'):
        return 'failure' if has('失败') or has('没能拿到') or has('真可惜') else 'settlement'
    if has('获得代币') and (has('得分牌型') or has('加倍')) and (has('再玩一次') or has('再来一次') or has('结束')):
        return 'settlement'
    if has('是否挑战') or (has('挑战') and has('算了') and (has('连续成功') or has('获得额') or has('Congratulations'))):
        return 'challenge'
    if has('你觉得下一张') and has('数字一样'):
        return 'guess'
    if has('请选择要留下') and (has('替换') or has('现在这样就好')):
        return 'hold'
    if has('押注额') and has('押注并开始游戏'):
        return 'bet'
    if has('点击继续'):
        return 'reveal'
    return 'unknown'


def label(report, query):
    # Only short OCR labels, not descriptive sentences or unconfirmed CV shapes.
    rows = [t for t in report.texts if norm(t.get('text', '')).strip('×x✓✔√《<>/／').replace('再玩一次','再来一次') == norm(query)
            and t.get('confidence', 1) >= .8 and 'bounds' in t]
    if len(rows) == 1: return rows[0]
    names={'高':'hl_button_high','低':'hl_button_low','替换':'hl_button_replace','现在这样就好':'hl_button_keep_all',
           '算了':'hl_button_cashout','挑战':'hl_button_challenge','再来一次':'hl_button_retry',
           '押注并开始游戏':'hl_button_bet','点击继续':'hl_button_proceed','结束':'hl_button_end'}
    matches=[m for m in report.knowledge_matches if m.get('label')==names.get(query) and m.get('similarity',0)>=TEMPLATE_THRESHOLD]
    return matches[0] if len(matches)==1 else None


def amount_from_prompt(report):
    if 'high_low_reward_amount' in report.frame:
        return report.frame['high_low_reward_amount']
    text = ''.join(t.get('text', '') for t in report.texts)
    # The displayed amount is the NEXT reward; never read unrelated account balance.
    match = re.search(r'获得额会变成\s*([0-9,，]+)', text)
    if not match:
        return None
    number = int(match[1].replace(',', '').replace('，', ''))
    return number // 2 if number > 0 and number % 2 == 0 else None


def associated_amount(report, query):
    """Read a unique integer near a current OCR amount label, not account balance."""
    anchors = [t for t in report.texts if norm(t.get('text','')) == norm(query) and 'bounds' in t]
    if len(anchors) != 1:
        return None
    b = anchors[0]['bounds']
    height = report.frame.get('bounds',{}).get('height',0)
    candidates = []
    for t in report.texts:
        raw = norm(t.get('text','')).replace(',','').replace('，','')
        raw = re.sub(r'枚(?:代币)?$','',raw)
        if not re.fullmatch(r'[0-9]+', raw) or t.get('confidence',1) < .9 or 'bounds' not in t:
            continue
        n = t['bounds']
        dx = abs(n['x']+n['width']/2 - (b['x']+b['width']/2))
        dy = abs(n['y']+n['height']/2 - (b['y']+b['height']/2))
        if dx <= max(b['width'],n['width'])*1.5 and dy <= max(b['height']*4,height*.08):
            candidates.append(int(raw))
    return candidates[0] if len(candidates) == 1 else None


def settlement_amount(report):
    if 'high_low_settlement_amount' in report.frame:
        return report.frame['high_low_settlement_amount']
    for query in ('获得额','获得代币','获得奖励'):
        amount = associated_amount(report, query)
        if amount is not None:
            return amount
    text = ''.join(t.get('text','') for t in report.texts)
    match = re.search(r'(?:获得了|获得代币|获得奖励)\s*([0-9,，]+)', text)
    return int(match[1].replace(',','').replace('，','')) if match else None


def rewarded(cards):
    ranks = [c['rank'] for c in cards if c['rank'] != 0]
    wild = sum(c['rank'] == 0 for c in cards)
    counts = sorted(Counter(ranks).values(), reverse=True)
    if not counts:
        return False
    if counts[0] + wild >= 3 or sum(n >= 2 for n in counts) >= 2:
        return True
    if len(set(c['suit'] for c in cards if c['rank'])) == 1:
        return True
    # A is high; A2345 remains unconfirmed and is not assumed.
    return len(set(ranks)) == len(ranks) and any(set(ranks) <= set(range(low, low + 5)) for low in range(2, 11))


def choose_hold(cards):
    if len(cards) != 5:
        raise ValueError('必须识别五张牌')
    counts = Counter(c['rank'] for c in cards if c['rank'])
    if sorted(counts.values()) == [1,2,2] and not any(c['rank']==0 for c in cards):
        return tuple(i for i,c in enumerate(cards) if counts[c['rank']]==2)
    if rewarded(cards):
        return tuple(range(5))  # Preserve guaranteed access to the reward.
    jokers = [i for i, c in enumerate(cards) if c['rank'] == 0]
    counts = Counter(c['rank'] for c in cards if c['rank'])
    pairs = [r for r, n in counts.items() if n >= 2]
    if pairs:
        return tuple(i for i, c in enumerate(cards) if c['rank'] in pairs or i in jokers)
    # User baseline, not claimed mathematically optimal. Four-card opportunities
    # precede three-card suited straight opportunities; retain Joker throughout.
    for size in (4, 3):
        from itertools import combinations
        for indices in combinations(range(5), size):
            if not set(jokers) <= set(indices):
                continue
            ordinary = [cards[i] for i in indices if cards[i]['rank']]
            ranks = [c['rank'] for c in ordinary]
            suited = len(set(c['suit'] for c in ordinary)) == 1
            straight = len(set(ranks)) == len(ranks) and any(set(ranks) <= set(range(low, low + 5)) for low in range(2, 11))
            if (size == 4 and (suited or straight)) or (size == 3 and suited and straight):
                return indices
    return tuple(jokers)


class CardVision:
    """CV boxes from THIS image; normalized local corner templates, threshold .5."""
    def __init__(self, template_dir):
        self.directory = Path(template_dir)
        self.templates = {}
        self._stamp = None
        self.last_match = {}

    @staticmethod
    def glyph(image):
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        binary = (((v < 110) & (s < 140)) | (((h < 15) | (h > 165)) & (s > 110) & (v > 70))).astype('uint8') * 255
        ys, xs = np.where(binary != 0)
        if not len(xs):
            return None
        binary = binary[ys.min():ys.max()+1, xs.min():xs.max()+1]
        scale = 48 / max(binary.shape)
        small = cv2.resize(binary, (max(1, round(binary.shape[1]*scale)), max(1, round(binary.shape[0]*scale))), interpolation=cv2.INTER_NEAREST)
        result = np.zeros((64, 64), np.uint8)
        y, x = (64-small.shape[0])//2, (64-small.shape[1])//2
        result[y:y+small.shape[0], x:x+small.shape[1]] = small
        return result

    def refresh(self):
        files = sorted(self.directory.glob('hl_*.png'))
        stamp = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files)
        if stamp == self._stamp:
            return
        templates = {}
        for p in files:
            image = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
            if image is not None:
                mask = self.glyph(image)
                if mask is not None:
                    # Optional _red/_black or numbered variants share a label.
                    name = p.stem
                    for base in TEMPLATE_NAMES:
                        if name == base or name.startswith(base + '_'):
                            templates.setdefault(base, []).append(mask)
                            break
        self.templates, self._stamp = templates, stamp

    def missing(self):
        self.refresh()
        return [name for name in TEMPLATE_NAMES if name not in self.templates]

    def missing_assets(self):
        missing=self.missing()
        for button in ('high','low'):
            name='hl_button_'+button
            path=self.directory/(name+'.png')
            try:
                image=cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)
                if image is None or min(image.shape[:2])<3: missing.append(name)
            except (OSError,cv2.error): missing.append(name)
        return missing

    def match(self, image, names):
        self.last_match={}
        is_suit=bool(names) and all(name.startswith('hl_suit_') for name in names)
        if is_suit:
            hue,sat,val=cv2.split(cv2.cvtColor(image,cv2.COLOR_BGR2HSV))
            red=int(np.count_nonzero(((hue<15)|(hue>165))&(sat>110)&(val>70)))
            black=int(np.count_nonzero((val<110)&(sat<140)))
            if red==black==0: return None,0.0
            color_names=('hl_suit_heart','hl_suit_diamond') if red>black else ('hl_suit_spade','hl_suit_club')
            names=[name for name in names if name in color_names]
        mask = self.glyph(image)
        if mask is None:
            return None, 0.0
        candidates = []
        for name in names:
            scores = []
            for template in self.templates.get(name, []):
                padded = cv2.copyMakeBorder(template, 3, 3, 3, 3, cv2.BORDER_CONSTANT)
                scores.append(float(cv2.minMaxLoc(cv2.matchTemplate(padded, mask, cv2.TM_CCOEFF_NORMED))[1]))
            if scores:
                candidates.append((max(scores), name))
        candidates.sort(reverse=True)
        if not candidates:
            return None, 0.0
        score, name = candidates[0]
        margin = score - candidates[1][0] if len(candidates) > 1 else 1
        accepted=score>=TEMPLATE_THRESHOLD
        self.last_match={'best':name,'score':score,'margin':margin,'candidates':candidates[:2]}
        return (name if accepted else None), score

    @staticmethod
    def boxes(image):
        height, width = image.shape[:2]
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 230), (180, 45, 255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if .1*width < w < .2*width and .25*height < h < .5*height and .58 < w/h < .82 and .2*height < y < .6*height:
                boxes.append((x, y, w, h))
        return sorted(boxes)

    def read(self, image, origin, phase, *, best_effort=False):
        self.refresh()
        boxes = self.boxes(image)
        if phase == 'hold' and len(boxes) != 5:
            return [], ['未检测到五个独立正面牌框']
        if phase == 'guess':
            # Previous face-up cards remain visible; the latest is rightmost.
            if not boxes:
                return [], ['等待当前基准牌完整出现']
            boxes = [max(boxes, key=lambda box: box[0])]
        if phase not in ('hold', 'guess'):
            return [], []
        missing = self.missing()
        if missing:
            return [], ['缺少卡牌模板：'+', '.join(missing)]
        cards, errors = [], []
        for card_index,(x, y, w, h) in enumerate(boxes,1):
            # Locate ink components in the inset upper-left corner. Rank and suit
            # are separated by their horizontal lines, not the central artwork.
            corner = image[y+round(h*.025):y+round(h*.23), x+round(w*.015):x+round(w*.23)]
            hsv = cv2.cvtColor(corner, cv2.COLOR_BGR2HSV)
            hue, sat, val = cv2.split(hsv)
            ink = (((val < 110) & (sat < 140)) | (((hue < 15) | (hue > 165)) & (sat > 110) & (val > 70)))
            rows = np.where(ink.any(axis=1))[0]
            groups = []
            for row in rows:
                if not groups or row > groups[-1][-1]+1:
                    groups.append([int(row)])
                else:
                    groups[-1].append(int(row))
            groups = [g for g in groups if len(g) >= 3]
            joker, js = self.match(corner, ['hl_joker'])
            if joker is None:
                # User templates may contain the full Joker face rather than
                # only its corner. Compare like-for-like before ordinary ranks.
                joker, js = self.match(image[y:y+h,x:x+w], ['hl_joker'])
            if joker:
                rank, suit, score = 0, 'joker', js
            elif len(groups) >= 2 or best_effort:
                if len(groups)>=2:
                    top, bottom = groups[0], groups[1]
                else:
                    # Fixed upper-left rank/suit slots provide candidates when
                    # component separation fails; never synthesize a card value.
                    split=max(1,round(corner.shape[0]*.55))
                    top=list(range(split));bottom=list(range(split,corner.shape[0]))
                rank_name, rs = self.match(corner[top[0]:top[-1]+1], ['hl_rank_'+r for r in RANKS])
                rank_diagnostic=dict(self.last_match)
                suit_name, ss = self.match(corner[bottom[0]:bottom[-1]+1], ['hl_suit_'+s for s in SUITS])
                if best_effort:
                    rank_name=rank_name or rank_diagnostic.get('best')
                    suit_name=suit_name or self.last_match.get('best')
                if rank_name is None or suit_name is None:
                    errors.append('第'+str(card_index)+'张牌点/花色不确定；点数候选='+str(rank_diagnostic)+'；花色候选='+str(self.last_match))
                    continue
                value = rank_name.removeprefix('hl_rank_')
                rank = {'j':11, 'q':12, 'k':13, 'a':14}.get(value)
                rank = rank if rank is not None else int(value)
                suit, score = suit_name.removeprefix('hl_suit_'), min(rs, ss)
            else:
                errors.append('第'+str(card_index)+'张无法分离普通角标，鬼牌角标/整牌模板均未通过0.5核验')
                continue
            # Pink hold badge directly overlaps/below the currently detected card.
            badge = image[min(image.shape[0], y+h-18):min(image.shape[0], y+h+40), x:x+w]
            held = False
            if badge.size:
                b = cv2.cvtColor(badge, cv2.COLOR_BGR2HSV)
                pink = cv2.inRange(b, (150, 120, 160), (179, 255, 255))
                held = bool(np.count_nonzero(pink) > w*8)
            cards.append({'rank':rank, 'suit':suit, 'held':held, 'score':score,
                          'bounds':Rect(x+origin[0], y+origin[1], w, h).to_dict()})
        if len(set((c['rank'], c['suit']) for c in cards)) != len(cards):
            errors.append('检测到重复牌，拒绝决策')
        if phase == 'guess' and any(c['rank'] == 0 for c in cards):
            errors.append('猜大小不应出现鬼牌')
        return cards, errors


class GreedCardsPlay:
    def __init__(self, *, daily_collected=0, max_rounds=200, max_loss=10000, stage=0):
        if daily_collected is not None and (type(daily_collected) is not int or daily_collected < 0):
            raise ValueError('每日累计必须是非负整数或未知')
        if type(max_rounds) is not int or max_rounds < 1 or type(max_loss) is not int or max_loss < 50:
            raise ValueError('需要正数局数和至少50的亏损上限')
        if stage not in (0, 1, 2):
            raise ValueError('阶段必须为0/1/2')
        self.daily = daily_collected
        self.max_rounds, self.max_loss, self.stage = max_rounds, max_loss, stage
        self.rounds = self.fees = self.earned = 0
        self.current = None
        self.pending = None
        self.round_active = False
        self.hold_plan = None
        self.hand_key = None
        self.settlement_seen = None
        self.settlement_accounted = False
        self.failure_confirmed = False
        self.guess_wins = self.guess_losses = self.cashouts = 0
        self.retry_clicks = 0
        self.round_history = []

    def handoff(self, state, message):
        return {'state':state, 'outcome':'unknown', 'verified':False, 'handoff':'local_play', 'message':message}

    def ledger(self):
        return {'daily_collected':self.daily, 'stage':self.stage, 'rounds':self.rounds,
                'entry_fees':self.fees, 'collected':self.earned, 'net':self.earned-self.fees,
                'lost_rounds':sum(r['outcome']=='loss' for r in self.round_history),
                'loss_amount':sum(-r['net'] for r in self.round_history if r['outcome']=='loss'),
                'winning_net':sum(r['net'] for r in self.round_history if r['outcome']=='win'),
                'round_history':list(self.round_history),
                'current_reward':self.current, 'pending':self.pending,
                'guess_wins':self.guess_wins,'guess_losses':self.guess_losses,'cashouts':self.cashouts,
                'guess_win_rate':self.guess_wins/(self.guess_wins+self.guess_losses) if self.guess_wins+self.guess_losses else None,
                'return_on_fees':(self.earned-self.fees)/self.fees if self.fees else None,
                'retry_clicks':self.retry_clicks}

    def expected_states(self):
        if self.pending:
            return {
                'bet':{'bet','hold'},
                'hold':{'hold'},
                'hold_batch':{'hold'},
                'replace':{'hold','reveal','challenge','failure'},
                'proceed':{'reveal','challenge','failure'},
                'challenge':{'challenge','guess'},
                'guess':{'guess','challenge','failure','settlement'},
                'cashout':{'challenge','settlement'},
                'retry':{'failure','settlement','bet'},
            }.get(self.pending['kind'],set())
        if self.round_active: return {'hold','reveal','challenge','guess','failure','settlement'}
        if self.failure_confirmed: return {'failure','bet'}
        return {'bet','settlement'}

    def decide(self, report, cards=(), errors=()):
        state = classify(report)
        if (self.pending or self.round_active or self.failure_confirmed) and state not in self.expected_states() and state != 'daily_limit':
            return {'state':state,'action':'wait','message':'等待预期阶段：'+','.join(sorted(self.expected_states()))}
        # Retry dismisses a result overlay; its old guess/reveal background is
        # not evidence that a new round started. Wait for the betting page.
        if self.pending and self.pending['kind'] == 'retry' and state not in ('bet', self.pending['state']):
            return {'state':state, 'action':'wait'}
        if self.failure_confirmed and not self.round_active and state not in ('failure','bet','daily_limit'):
            return {'state':state, 'action':'wait'}
        if state=='hold' and errors:
            if len(cards)==5 and all(error=='检测到重复牌，拒绝决策' for error in errors):
                errors=[]
            else:
                return {'state':state,'action':'wait','card_retry':True,'message':'牌面识别未完整，继续检测：'+'; '.join(errors)}
        if errors:
            if state == 'guess' and list(errors) == ['等待当前基准牌完整出现']:
                return {'state':state, 'action':'wait', 'message':errors[0]}
            return self.handoff(state, '; '.join(errors))
        if state == 'daily_limit':
            return {'state':state, 'outcome':'success', 'verified':True, 'message':'屏幕确认每日上限'}
        def click(query, kind):
            target = label(report, query)
            if not target:
                return {'state':state,'action':'wait','waiting_for':query,'message':'等待当前按钮出现或识别稳定：'+query}
            return {'state':state, 'action':'click', 'target':target['bounds'], 'kind':kind}
        def supplement():
            pending=self.pending
            if state != pending['state'] or pending.get('supplements',0)>=3 or time.monotonic()-pending['sent_at']<.5:
                return {'state':state,'action':'wait'}
            kind=pending['kind']
            if kind in ('hold','hold_batch'):
                if len(cards)!=5 or tuple((c['rank'],c['suit']) for c in cards)!=self.hand_key:
                    return {'state':state,'action':'wait'}
                changes=[(i,c) for i,c in enumerate(cards) if c['held']!=(i in self.hold_plan)]
                if not changes: return {'state':state,'action':'wait'}
                i,c=changes[0]
                decision={'state':state,'action':'click','target':c['bounds'],'kind':'hold','index':i,'held':i in self.hold_plan}
            elif kind=='guess':
                if len(cards)!=1 or (cards[0]['rank'],cards[0].get('suit'))!=pending.get('basis'):
                    return {'state':state,'action':'wait'}
                decision=click('高' if cards[0]['rank']<=8 else '低','guess')
                decision['basis']=pending['basis']
            elif kind=='proceed' and report.frame.get('high_low_template_state')=='reveal':
                b=report.frame['bounds']
                decision={'state':state,'action':'click','kind':kind,'target':Rect(b['x']+b['width']//2-5,b['y']+b['height']//2-5,10,10).to_dict()}
            else:
                queries={'bet':'押注并开始游戏','replace':'现在这样就好' if len(cards)==5 and all(c['held'] for c in cards) else '替换',
                         'proceed':'点击继续','challenge':'挑战','cashout':'算了','retry':'再来一次'}
                decision=click(queries[kind],kind)
            if decision['action']=='click': decision['supplement']=True
            return decision
        if self.pending:
            kind = self.pending['kind']
            if kind == 'bet' and state == 'hold':
                self.rounds += 1; self.fees += 50; self.round_active = True
                self.pending = None
            elif kind == 'hold_batch' and state == 'hold':
                if len(cards)!=5 or tuple((c['rank'],c['suit']) for c in cards)!=self.hand_key:
                    return {'state':state,'action':'wait'}
                if all(c['held']==(i in self.hold_plan) for i,c in enumerate(cards)):
                    self.pending=None
                else: return supplement()
            elif kind == 'hold' and state == 'hold':
                if len(cards) != 5:
                    return self.handoff(state, '留牌反馈缺少五张牌')
                index = self.pending['index']
                if tuple((c['rank'], c['suit']) for c in cards) != self.hand_key:
                    return self.handoff(state, '留牌操作期间牌面变化')
                if cards[index]['held'] == self.pending['held']:
                    self.pending = None
                else:
                    return supplement()
            elif kind == 'retry' and state == self.pending['state']:
                return supplement()
            elif kind == 'retry' and state == 'bet':
                self.pending = None; self.retry_clicks = 0
            elif kind in ('replace', 'proceed', 'challenge') and state in self.expected_states() and state != self.pending['state']:
                self.pending = None
            elif kind == 'guess' and state == 'challenge':
                observed = amount_from_prompt(report)
                if observed is None or self.current is None or observed != self.current*2:
                    return self.handoff(state, '成功弹窗金额未能核对翻倍')
                self.guess_wins += 1
                self.current = observed; self.pending = None
            elif kind == 'guess' and state == 'guess':
                # Identical rank can be an unchanged frame OR a tie. Do not repeat
                # input without explicit tie evidence; hand off after timeout.
                tie = any('平局' in t.get('text','') for t in report.texts)
                basis=self.pending.get('basis')
                if basis and len(cards)==1 and cards[0]['rank']==basis[0] and cards[0].get('suit')!=basis[1]:
                    tie=True
                if tie and len(cards) == 1:
                    self.pending = None
                else:
                    return supplement()
            elif kind == 'guess' and state == 'failure':
                self.guess_losses += 1
                self.pending = None
            elif kind in ('cashout', 'guess') and state == 'settlement':
                if kind == 'guess':
                    if self.current is None: return self.handoff(state, '最终翻倍缺少奖励上下文')
                    observed=settlement_amount(report)
                    if observed != self.current*2:
                        return {'state':state,'action':'wait','message':f'等待稳定结算金额：识别{observed}，预期{self.current*2}'}
                    self.current *= 2
                    self.guess_wins += 1
                self.pending = None
            else:
                return supplement()
        if state == 'bet':
            if self.daily is None:
                return self.handoff(state, '请提供今天已收取奖励累计，不能从缩略余额估计')
            if self.daily >= 20000:
                return {'state':state, 'outcome':'success', 'verified':True, 'message':'已核对的当日收益达到门槛'}
            if self.rounds >= self.max_rounds:
                return self.handoff(state, f'已到局数上限：{self.rounds}/{self.max_rounds}')
            if self.fees-self.earned >= self.max_loss:
                return self.handoff(state, f'已到净亏损上限：{self.fees-self.earned}/{self.max_loss}')
            self.failure_confirmed = False
            self.current = None; self.hold_plan = self.hand_key = None; self.settlement_seen = None
            self.settlement_accounted = False
            return click('押注并开始游戏', 'bet')
        if state == 'hold':
            if not self.round_active:
                return self.handoff(state, '从中途接管留牌页需确认本局下注与收益账目')
            if len(cards) != 5:
                return self.handoff(state, '无法完整识别五张牌')
            key = tuple((c['rank'],c['suit']) for c in cards)
            if self.hold_plan is None:
                self.hold_plan, self.hand_key = choose_hold(cards), key
            if key != self.hand_key:
                return self.handoff(state, '留牌期间牌面意外变化')
            for i,c in enumerate(cards):
                held = i in self.hold_plan
                if c['held'] != held:
                    return {'state':state, 'action':'click', 'target':c['bounds'], 'kind':'hold', 'index':i, 'held':held}
            if all(c['held'] for c in cards):
                return click('现在这样就好', 'replace')
            return click('替换', 'replace')
        if state == 'reveal':
            if not self.round_active:
                return self.handoff(state, '未知本局上下文')
            if report.frame.get('high_low_reward_amount') is not None:
                self.current=report.frame['high_low_reward_amount']
            if report.frame.get('high_low_template_state')=='reveal':
                b=report.frame['bounds']
                return {'state':state,'action':'click','kind':'proceed','target':Rect(b['x']+b['width']//2-5,b['y']+b['height']//2-5,10,10).to_dict()}
            return click('点击继续', 'proceed')
        if state == 'challenge':
            amount = amount_from_prompt(report)
            if amount is None: amount = associated_amount(report, '获得额')
            if not self.round_active or amount is None:
                return self.handoff(state, '缺少本局或当前奖励；需带下一次奖励文字的完整截图')
            if self.current is not None and amount != self.current:
                return self.handoff(state, '挑战金额与本地奖励账目不一致')
            self.current = amount
            if self.daily is None:
                return self.handoff(state, '当日收益未知')
            if self.daily > 18000:
                self.stage = 2
            # Stage 1 aims near 6400 while keeping total BELOW daily gate;
            # stages 0/2 pursue the single-run gate with allowed overshoot.
            cashout = amount >= 10000
            if self.stage == 1:
                cashout = amount >= 6400 or self.daily+amount*2 >= 20000
                if self.daily+amount >= 20000:
                    return self.handoff(state, '当前奖励无法保留第三笔机会，请人工决定')
            return click('算了' if cashout else '挑战', 'cashout' if cashout else 'challenge')
        if state == 'guess':
            if not self.round_active or self.current is None or len(cards) != 1:
                return self.handoff(state, '缺少当前牌点或本局奖励上下文')
            decision=click('高' if cards[0]['rank'] <= 8 else '低', 'guess')
            if 'action' in decision: decision['basis']=(cards[0]['rank'],cards[0].get('suit'))
            return decision
        if state == 'failure':
            if not self.round_active and not self.failure_confirmed:
                return self.handoff(state, '未知失败所属对局')
            if self.round_active:
                self.round_history.append({'round':self.rounds,'outcome':'loss','collected':0,'fee':50,'net':-50})
            self.current = 0; self.round_active = False; self.failure_confirmed = True
            self.retry_clicks = 0
            return click('再来一次', 'retry')
        if state == 'settlement':
            amount = settlement_amount(report)
            if not self.round_active:
                if self.settlement_accounted:
                    if self.daily >= 20000 or label(report,'结束') is not None:
                        return {'state':state,'outcome':'success','verified':True,'message':'已确认结算；每日门槛或结束按钮已出现'}
                    return click('再来一次','retry')
                return self.handoff(state, '结算所属对局未知，需人工确认账目')
            if amount is None or self.current is None or amount != self.current:
                return {'state':state,'action':'wait','message':f'等待稳定结算金额：识别{amount}，预期{self.current}'}
            if self.settlement_seen != amount:
                self.settlement_seen = amount
                return {'state':state, 'action':'wait'}
            self.settlement_accounted = True
            self.daily += amount; self.earned += amount; self.cashouts += 1
            self.round_history.append({'round':self.rounds,'outcome':'win','collected':amount,'fee':50,'net':amount-50})
            self.round_active = False
            self.stage = min(2, self.stage + 1)
            if self.daily >= 20000 or label(report,'结束') is not None:
                return {'state':state, 'outcome':'success', 'verified':True, 'message':'精确结算已确认；每日收益门槛或结束按钮已出现，停止继续下注'}
            return click('再来一次', 'retry')
        return {'state':state, 'action':'wait'}

    def committed(self, decision):
        supplements=(self.pending.get('supplements',0)+1) if decision.get('supplement') and self.pending else 0
        if decision['kind']=='retry':
            if self.pending and self.pending['kind']=='retry': self.retry_clicks += 1
            else: self.retry_clicks = 0
        self.pending = {k:decision[k] for k in ('kind','state','index','held','basis') if k in decision}
        self.pending['sent_at'] = time.monotonic()
        self.pending['supplements'] = supplements

    def run(self, observe, computer, progress=lambda message:None, *, should_yield=lambda:False, timeout=1800, clock=time.monotonic):
        if isinstance(observe,PlayObserver): observe.context=self
        started = clock(); unknown_since = None; pending_since = None
        def result(value, observation=None):
            ledger=self.ledger()
            progress(f"本次统计：玩了{self.rounds}局，收取{self.earned}，赢局净赚{ledger['winning_net']}，输了{ledger['lost_rounds']}局（亏损{ledger['loss_amount']}），下注成本{self.fees}，净收益{self.earned-self.fees:+d}。")
            if self.round_active or (self.pending and self.pending['kind']=='bet'):
                progress('存在未结算或下注待确认的对局，收益统计仅包含已确认结果。')
            return {**value, 'model_version':VERSION, 'ledger':self.ledger(),
                    'screen':observation['report'].to_dict() if observation else None,
                    'elapsed_seconds':round(clock()-started,3)}
        try:
            if not computer.live:
                return result(self.handoff('dry_run', '模拟模式不发送输入；可离线检查decide'))
            while clock()-started < timeout:
                if getattr(computer,'stopped',False):
                    return result({'outcome':'failure','verified':False,'message':'用户停止小游戏组件'})
                if should_yield():
                    return result({**self.handoff('guidance','收到人工引导，释放控制权'), 'handoff':'human_guidance'})
                observation = observe()
                if getattr(computer,'stopped',False):
                    return result({'outcome':'failure','verified':False,'message':'用户停止，取消未执行输入'},observation)
                if should_yield():
                    return result({**self.handoff('interrupted','人工引导取消未执行输入'),'handoff':'human_guidance'}, observation)
                report = observation['report']
                errors=observation.get('errors',[])
                transient=classify(report) in ('hold','guess') and errors and all(('点/花色不确定' in error or '未检测到五个' in error or '无法分离普通角标' in error or '等待当前基准牌' in error) for error in errors)
                previous_cashouts=self.cashouts
                decision = ({'state':classify(report),'action':'wait','card_retry':True} if transient else self.decide(report, observation.get('cards',[]),errors))
                if self.cashouts != previous_cashouts and isinstance(observe,PlayObserver):
                    from modular_agent.local_models import save_play_checkpoint
                    save_play_checkpoint(observe.root,self.ledger())
                    progress(f'已保存今日累计奖励：{self.daily}')
                progress('小游戏状态：'+decision['state'])
                if report.frame.get('ocr_fallback_reason'): progress('模板判据不足，单次OCR分支：'+report.frame['ocr_fallback_reason'])
                if 'outcome' in decision:
                    return result(decision, observation)
                if decision['action'] == 'wait':
                    if decision.get('card_retry'):
                        unknown_since = None; pending_since = None
                    elif self.pending:
                        if pending_since is None: pending_since = clock()
                        if clock()-pending_since >= 10:
                            return result(self.handoff(decision['state'],'连续10秒未确认输入后的预期反馈，交回顶层处理'), observation)
                    else:
                        if unknown_since is None: unknown_since = clock()
                        if clock()-unknown_since >= 10:
                            return result(self.handoff(decision['state'],('等待按钮 '+decision['waiting_for']+' 连续10秒仍未唯一定位') if decision.get('waiting_for') else '未知或过渡状态连续10秒'), observation)
                    if decision.get('waiting_for'): progress(decision['message'])
                    actions = [Action('wait',arguments={'duration':.1})]
                else:
                    unknown_since = None
                    if not decision.get('supplement'):
                        pending_since = clock()
                    game = next((w for w in report.windows if w.get('handle') == report.frame.get('target_window_handle')), None)
                    if not game or not game.get('foreground') or game.get('minimized') or report.frame.get('masked_agent_regions'):
                        return result(self.handoff(decision['state'],'游戏不在前台或被遮挡'), observation)
                    bounds = decision['target']
                    frame = report.frame['bounds']
                    x,y = bounds['x']+bounds['width']//2, bounds['y']+bounds['height']//2
                    if not (frame['x'] <= x < frame['x']+frame['width'] and frame['y'] <= y < frame['y']+frame['height']):
                        return result(self.handoff(decision['state'],'识别目标超出当前截图'), observation)
                    progress(f'准备点击：{decision["kind"]}；当前目标中心 ({x}, {y})')
                    if getattr(computer,'backend',None) is not None:
                        positioning=computer.run_actions([Action('key_down',arguments={'key':'alt'}),Action('move_to',arguments={'x':x,'y':y}),Action('wait',arguments={'duration':.1})])
                        if not all(r.outcome==Outcome.SUCCESS for r in positioning):
                            return result(self.handoff(decision['state'],'点击前鼠标定位失败，未发送点击'),observation)
                        cursor=computer.perform(Action('cursor'))
                        actual=cursor.data
                        progress('鼠标落点：'+str(actual))
                        if cursor.outcome!=Outcome.SUCCESS or abs(actual.get('x',-99999)-x)>4 or abs(actual.get('y',-99999)-y)>4:
                            return result({**self.handoff(decision['state'],'鼠标实际落点偏离当前目标，未发送点击'),'requested_click':{'x':x,'y':y},'actual_cursor':actual},observation)
                    # Current capture already verified foreground. Do not restore
                    # the game again after Alt/cursor positioning.
                    actions = []
                    if decision['kind']=='hold':
                        changes=[(i,c) for i,c in enumerate(observation['cards']) if c['held']!=(i in self.hold_plan)]
                        progress('本次选牌计划：'+','.join(str(i+1) for i,c in changes)+'；点击后统一核对')
                        for index,(i,c) in enumerate(changes):
                            b=c['bounds'];cx=b['x']+b['width']//2;cy=b['y']+b['height']//2
                            if not (frame['x']<=cx<frame['x']+frame['width'] and frame['y']<=cy<frame['y']+frame['height']):
                                return result(self.handoff('hold','选牌计划超出当前截图，未执行批量点击'),observation)
                            actions.append(Action('click',arguments={'x':cx,'y':cy,'modifiers':['alt'],'duration':.08}))
                            if index<len(changes)-1: actions.append(Action('wait',arguments={'duration':.1}))
                        decision={**decision,'kind':'hold_batch'}
                    else: actions.append(Action('click',arguments={'x':x,'y':y,'modifiers':['alt'],'duration':.08}))
                results=[]
                for action in actions:
                    if should_yield():
                        return result({**self.handoff('guidance','人工引导中断输入，选牌可能部分完成，请核对标记'),'handoff':'human_guidance'},observation)
                    dispatched=computer.run_actions([action])
                    results.extend(dispatched)
                    if len(dispatched)!=1 or dispatched[0].outcome!=Outcome.SUCCESS: break
                if len(results) != len(actions) or not all(r.outcome == Outcome.SUCCESS for r in results):
                    return result({'outcome':'failure','verified':False,'message':'输入失败，动作可能部分执行'}, observation)
                if decision['action'] != 'wait':
                    if getattr(computer,'backend',None) is not None: computer.perform(Action('key_up',arguments={'key':'alt'}))
                    self.committed(decision)
            return result(self.handoff('timeout',f'小游戏组件达到总时长上限（{timeout}秒），当前对局未自动结算；需人工接管'))
        except Exception as error:
            return result({'outcome':'failure','verified':False,'message':'小游戏组件异常：'+str(error)})
        finally:
            computer.release_all()

class PlayObserver:
    """One current capture supplies OCR, CV boxes and all click coordinates."""
    def __init__(self, root, vision, computer, profile):
        self.root, self.vision, self.computer, self.profile = Path(root), vision, computer, profile
        self._button_cache={}
        self._scale_hints={}
        self.template_scales=tuple(profile.get('local_models',{}).get('greed_cards_play',{}).get('template_scales',[1.0]))
        self._hand_masks=None
        self._last_diagnostic=0
        self.cards = CardVision(self.root/'domains'/'hololive_dreams'/'data'/'high_low_templates')

    @staticmethod
    def spatial_match_reason(score, second):
        if score < TEMPLATE_THRESHOLD: return 'below_threshold'
        if second >= TEMPLATE_THRESHOLD and score-second < SPATIAL_MATCH_GAP-1e-9:
            return 'ambiguous'
        return 'matched'

    def _templates(self,image,origin,report):
        gray=cv2.GaussianBlur(cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),80,160),(3,3),0)
        diagnostics={}
        names=['hl_state_reveal','hl_state_failure','hl_state_settlement']+['hl_button_'+n for n in ('bet','replace','keep_all','high','low','cashout','challenge','retry','replay','end')]
        context=getattr(self,'context',None)
        if context is not None:
            by_state={'bet':['hl_button_bet'],'hold':['hl_button_replace','hl_button_keep_all'],
                'guess':['hl_button_high','hl_button_low'],'challenge':['hl_button_cashout','hl_button_challenge'],
                'reveal':['hl_state_reveal'],'failure':['hl_state_failure','hl_button_cashout','hl_button_retry'],
                'settlement':['hl_state_settlement','hl_button_retry','hl_button_replay','hl_button_end']}
            selected={name for state in context.expected_states() for name in by_state.get(state,[])}
            names=[name for name in names if name in selected]
            if context.pending and context.pending['kind']=='hold_batch' and context.hold_plan is not None:
                wanted='hl_button_keep_all' if len(context.hold_plan)==5 else 'hl_button_replace'
                names=[name for name in names if name not in ('hl_button_replace','hl_button_keep_all') or name==wanted]
        for name in names:
            path=self.cards.directory/(name+'.png')
            if not path.exists():
                diagnostics[name]={'reason':'missing_file'};continue
            stamp=(str(path),path.stat().st_mtime_ns,path.stat().st_size)
            patches=self._button_cache.get(stamp)
            if patches is None:
                template=cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_GRAYSCALE)
                if template is None: diagnostics[name]={'reason':'unreadable'};continue
                if name.startswith('hl_button_'):
                    th,tw=template.shape
                    template=template[int(th*.22):int(th*.78),int(tw*.25):int(tw*.85)]
                patches=[(scale,cv2.GaussianBlur(cv2.Canny((template if scale==1 else cv2.resize(template,None,fx=scale,fy=scale)),80,160),(3,3),0)) for scale in self.template_scales]
                self._button_cache[stamp]=patches
            height,width=gray.shape
            if name=='hl_state_reveal': roi=(.25,.05,.75,.25)
            elif name=='hl_state_settlement': roi=(.5,.2,.95,.4)
            elif name=='hl_state_failure': roi=(.3,.1,.8,.4)
            elif name=='hl_button_high': roi=(.65,.35,.99,.60)
            elif name=='hl_button_low': roi=(.65,.55,.99,.82)
            elif name=='hl_button_bet': roi=(.3,.72,.75,.87)
            elif name in ('hl_button_replace','hl_button_keep_all'): roi=(.3,.7,.75,.99)
            elif name in ('hl_button_challenge','hl_button_retry','hl_button_replay','hl_button_end'): roi=(.77,.8,.99,.99)
            else: roi=(.58,.8,.99,.99)
            left,top,right,bottom=[int(value*(width if i%2==0 else height)) for i,value in enumerate(roi)]
            search=gray[top:bottom,left:right]
            best=None
            hint_key=(stamp,image.shape[:2])
            hint=self._scale_hints.get(hint_key)
            ordered=sorted(patches,key=lambda item:item[0]!=hint) if hint is not None else patches
            for scale,patch in ordered:
                h,w=patch.shape
                if h>search.shape[0] or w>search.shape[1]: continue
                scores=cv2.matchTemplate(search,patch,cv2.TM_CCOEFF_NORMED)
                _,score,_,point=cv2.minMaxLoc(scores)
                if best is None or score>best[0]:
                    x,y=point
                    scores[max(0,y-h//2):y+h//2+1,max(0,x-w//2):x+w//2+1]=-1
                    best=(float(score),x,y,w,h,float(scores.max()),scale)
                if scale==hint and score>=.85 and self.spatial_match_reason(score,best[5])=='matched': break
            if best is None: diagnostics[name]={'reason':'too_large'};continue
            score,x,y,w,h,second,scale=best
            reason=self.spatial_match_reason(score,second)
            diagnostics[name]={'score':score,'second_score':second,'spatial_gap':score-second,'required_spatial_gap':SPATIAL_MATCH_GAP,'reason':reason,'scale':scale}
            if reason=='matched':
                self._scale_hints[hint_key]=scale
                report.knowledge_matches.append({'label':'hl_button_retry' if name=='hl_button_replay' else name,'similarity':score,'bounds':Rect(x+left+origin[0],y+top+origin[1],w,h).to_dict(),'source':'template'})
        conflicting=[m for m in report.knowledge_matches if m['label'] in ('hl_button_replace','hl_button_keep_all','hl_button_bet')]
        if conflicting:
            best=max(conflicting,key=lambda m:m['similarity'])
            report.knowledge_matches=[m for m in report.knowledge_matches if m not in conflicting or m is best]
        # Challenge/retry/end occupy the same bottom-right control.
        rivals=[m for m in report.knowledge_matches if m['label'] in ('hl_button_challenge','hl_button_retry','hl_button_end')]
        kept=[]
        for candidate in sorted(rivals,key=lambda m:m['similarity'],reverse=True):
            box=Rect.from_bbox(candidate['bounds']['bbox'])
            if any(box.iou(Rect.from_bbox(other['bounds']['bbox']))>.2 for other in kept): continue
            kept.append(candidate)
        report.knowledge_matches=[m for m in report.knowledge_matches if m not in rivals or m in kept]
        # Bet is an enclosed white-bordered control, never the explanation below.
        if not any(m['label']=='hl_button_bet' for m in report.knowledge_matches): return diagnostics
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        outline=cv2.inRange(hsv,(0,0,215),(180,90,255))
        contours,_=cv2.findContours(outline,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        enclosures=[]
        ih,iw=image.shape[:2]
        for contour in contours:
            bx,by,bw,bh=cv2.boundingRect(contour)
            if .12*iw<bw<.4*iw and .035*ih<bh<.13*ih and bw/bh>2.5 and .72*ih<by<.87*ih and cv2.contourArea(contour)>.5*bw*bh:
                enclosures.append((bx,by,bw,bh))
        for match in list(report.knowledge_matches):
            if match['label']!='hl_button_bet': continue
            b=match['bounds'];cx=b['x']+b['width']/2-origin[0];cy=b['y']+b['height']/2-origin[1]
            valid=[box for box in enclosures if box[0]<cx<box[0]+box[2] and box[1]<cy<box[1]+box[3]]
            if not valid:
                report.knowledge_matches.remove(match);diagnostics['hl_button_bet']['reason']='no_button_enclosure'
            else:
                bx,by,bw,bh=max(valid,key=lambda box:box[2]*box[3])
                match['bounds']=Rect(bx+origin[0],by+origin[1],bw,bh).to_dict()
        return diagnostics

    @staticmethod
    def _phase(report):
        names={m['label'] for m in report.knowledge_matches}
        if 'hl_state_settlement' in names: return 'settlement'
        if 'hl_state_failure' in names: return 'failure'
        if 'hl_state_reveal' in names: return 'reveal'
        if {'hl_button_retry','hl_button_cashout'}<=names: return 'failure'
        if {'hl_button_challenge','hl_button_cashout'}<=names: return 'challenge'
        if {'hl_button_high','hl_button_low'}<=names: return 'guess'
        if names & {'hl_button_replace','hl_button_keep_all'}: return 'hold'
        if 'hl_button_bet' in names: return 'bet'
        return 'unknown'

    def _ocr(self,image,origin,windows,handle,region=None):
        return self.vision.analyze(image,origin=origin,windows=windows,
            environment='hololive_dreams',window_handle=handle,enable_ocr=True,
            enable_uia=False,enable_cv_buttons=False,enable_knowledge=False,ocr_max_side=960,region=region)

    def _branch_log(self,report,phase,diagnostics,reason,ocr_report):
        path=self.root/'runtime'/'high-low';path.mkdir(parents=True,exist_ok=True)
        with (path/'ocr-fallbacks.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps({'timestamp':time.time(),'reason':reason,'template_state':phase,
                'ocr_state':classify(ocr_report),'pending':getattr(getattr(self,'context',None),'pending',None),'missing_predicates':{k:v for k,v in diagnostics.items() if v['reason']!='matched'},
                'ocr_texts':ocr_report.texts,'matched_templates':[m['label'] for m in report.knowledge_matches]},ensure_ascii=False)+'\n')

    def _corner_masks(self,image,boxes):
        return [self.cards.glyph(image[y+round(h*.025):y+round(h*.23),x+round(w*.015):x+round(w*.23)]) for x,y,w,h in boxes]

    def _fast_holds(self,image,origin,boxes,context):
        if len(boxes)!=5 or self._hand_masks is None or context.hand_key is None: return None
        masks=self._corner_masks(image,boxes)
        for current,previous in zip(masks,self._hand_masks):
            if current is None or previous is None: return None
            score=float(cv2.matchTemplate(current,previous,cv2.TM_CCOEFF_NORMED)[0,0])
            if float(np.std(current))<1e-6 or float(np.std(previous))<1e-6 or not np.isfinite(score) or score<.85: return None
        cards=[]
        for (x,y,w,h),(rank,suit) in zip(boxes,context.hand_key):
            badge=image[min(image.shape[0],y+h-18):min(image.shape[0],y+h+40),x:x+w]
            pink=cv2.inRange(cv2.cvtColor(badge,cv2.COLOR_BGR2HSV),(150,120,160),(179,255,255))
            cards.append({'rank':rank,'suit':suit,'held':bool(np.count_nonzero(pink)>w*8),
                'bounds':Rect(x+origin[0],y+origin[1],w,h).to_dict(),'score':1.0})
        return cards

    def analyze(self, image, origin=(0,0), windows=(), handle=None):
        analyzed_at=time.monotonic()
        report=self.vision.analyze(image,origin=origin,windows=windows,environment='hololive_dreams',
            window_handle=handle,enable_ocr=False,enable_uia=False,enable_cv_buttons=False,enable_knowledge=False)
        if handle is not None: report.frame['target_window_handle']=handle
        report.frame['detail']='high_low_local'
        diagnostics=self._templates(image,origin,report)
        phase=self._phase(report)
        boxes=self.cards.boxes(image)
        if 'hl_button_bet' in {m['label'] for m in report.knowledge_matches} and not boxes: phase='bet'
        elif (phase=='hold' and len(boxes)!=5) or (phase=='bet' and boxes): phase='unknown'
        context=getattr(self,'context',None)
        expected=context.expected_states() if context is not None else None
        if expected is not None and phase not in expected: phase='unknown'
        needed={'failure':'再来一次','settlement':'再来一次','challenge':'挑战','guess':'高','hold':'替换','bet':'押注并开始游戏'}
        missing_button=phase in needed and label(report,needed[phase]) is None
        if phase=='hold' and label(report,'现在这样就好'): missing_button=False
        if phase=='settlement' and label(report,'结束'): missing_button=False
        fallback=phase=='unknown' or missing_button
        context=getattr(self,'context',None)
        pending=context.pending if context is not None else None
        fallback_key=(phase,tuple(sorted(m['label'] for m in report.knowledge_matches)),pending.get('sent_at') if pending else None)
        now=time.monotonic()
        if fallback:
            if getattr(self,'_fallback_since',None) is None: self._fallback_since=now
        else:
            self._fallback_since=None
        fallback_ready=fallback and now-self._fallback_since>=2
        if fallback_ready and getattr(self,'_fallback_key',None)!=fallback_key:
            ocr=self._ocr(image,origin,windows,handle)
            self._branch_log(report,phase,diagnostics,'state_missing' if phase=='unknown' else 'button_missing',ocr)
            report.frame['ocr_fallback_reason']='state_missing' if phase=='unknown' else 'button_missing'
            self._fallback_key=fallback_key
            report.texts=ocr.texts;report.timings_ms.update(ocr.timings_ms)
            if phase=='unknown':
                detected=classify(ocr)
                phase=detected if expected is None or detected in expected else 'unknown'
        elif not fallback: self._fallback_key=None
        if fallback and not fallback_ready: report.frame['template_retry_remaining']=round(max(0,2-(now-self._fallback_since)),3)
        report.frame['high_low_template_state']=phase
        if expected is not None: report.frame['expected_states']=sorted(expected)
        context=getattr(self,'context',None)
        if phase=='challenge' and context is not None and context.current is not None:
            report.frame['high_low_reward_amount']=context.current*(2 if context.pending and context.pending['kind']=='guess' else 1)
        if phase in ('reveal','settlement') or (phase=='challenge' and (context is None or context.current is None)):
            h,w=image.shape[:2]
            if phase=='reveal': x,y,rw,rh=int(w*.35),int(h*.70),int(w*.4),int(h*.19)
            elif phase=='settlement': x,y,rw,rh=int(w*.50),int(h*.23),int(w*.45),int(h*.2)
            else: x,y,rw,rh=0,0,w,h
            ocr=self._ocr(image,origin,windows,handle,[origin[0]+x,origin[1]+y,rw,rh])
            report.timings_ms['amount_ocr']=ocr.timings_ms.get('ocr',0)
            report.frame['amount_ocr_texts']=ocr.texts
            value=settlement_amount(ocr) if phase=='settlement' else amount_from_prompt(ocr) if phase=='challenge' else associated_amount(ocr,'获得额')
            if value is None and phase in ('reveal','settlement'):
                numbers=[]
                for t in ocr.texts:
                    match=re.fullmatch(r'([0-9,，]+)(?:枚)?',norm(t.get('text','')))
                    if match and t.get('confidence',0)>=.9: numbers.append(int(match[1].replace(',','').replace('，','')))
                if len(numbers)==1: value=numbers[0]
            if value is not None: report.frame['high_low_settlement_amount' if phase=='settlement' else 'high_low_reward_amount']=value
            else: report.texts.extend(ocr.texts)
        fast=None
        if phase=='hold' and context is not None and context.pending and context.pending['kind'] in ('hold','hold_batch'):
            fast=self._fast_holds(image,origin,boxes,context)
        if fast is not None:
            cards,errors=fast,[]
            report.frame['hold_marker_fast_path']=True
        else:
            cards,errors=self.cards.read(image,origin,phase,best_effort=phase=='hold')
            if phase=='hold' and not errors and len(cards)==5: self._hand_masks=self._corner_masks(image,boxes)
        if phase=='bet':
            missing=self.cards.missing_assets()
            if missing: errors.append('下注前素材检查未通过：'+', '.join(missing))
        if errors:
            if getattr(self,'_card_fallback_since',None) is None: self._card_fallback_since=time.monotonic()
        else: self._card_fallback_since=None
        if errors and time.monotonic()-self._card_fallback_since>=2 and not getattr(self,'_card_fallback_used',False):
            ocr=self._ocr(image,origin,windows,handle)
            self._branch_log(report,phase,diagnostics,'card_predicates_missing: '+'; '.join(errors),ocr)
            self._card_fallback_used=True
            # OCR does not safely recover suits; keep errors rather than invent cards.
        elif not errors: self._card_fallback_used=False
        report.frame['template_diagnostics']=diagnostics
        report.timings_ms['high_low_total']=(time.monotonic()-analyzed_at)*1000
        return {'report':report,'cards':cards,'errors':errors}

    def __call__(self):
        from modular_agent.agent.launcher import GameLauncher
        from modular_agent.perception.screen import capture_monitor
        windows = self.vision.desktop.windows()
        game = GameLauncher(self.vision, self.computer, self.profile)._window(windows)
        if not game or not game.get('foreground') or game.get('minimized'):
            raise RuntimeError('游戏必须已在前台；玩法模块不会启动或导航')
        image, frame = capture_monitor(0)
        screen = Rect(frame.left, frame.top, frame.width, frame.height)
        bounds = Rect.from_bbox(game['bounds']['bbox']).intersection(screen)
        if bounds.area != Rect.from_bbox(game['bounds']['bbox']).area:
            raise RuntimeError('游戏窗口不完整可见')
        occlusions = occluding_windows(windows,game)
        if occlusions:
            names='、'.join(w.get('title') or w.get('process_name') or str(w['handle']) for w in occlusions)
            raise RuntimeError('游戏被窗口遮挡：'+names+'；请移开后重试，未发送本轮输入')
        x,y = bounds.x-frame.left, bounds.y-frame.top
        image = image[y:y+bounds.height, x:x+bounds.width].copy()
        observed = self.analyze(image, (bounds.x,bounds.y), windows, game['handle'])
        fresh_windows=self.vision.desktop.windows()
        fresh=GameLauncher(self.vision,self.computer,self.profile)._window(fresh_windows)
        if not fresh or fresh['handle']!=game['handle'] or not fresh.get('foreground') or fresh.get('minimized') or fresh.get('bounds')!=game.get('bounds'):
            observed['errors'].append('识别期间窗口焦点或位置变化，丢弃当前目标')
        elif occluding_windows(fresh_windows,fresh):
            observed['errors'].append('识别期间出现新的遮挡窗口，丢弃当前目标')
        path = self.root/'runtime'/'high-low'
        path.mkdir(parents=True,exist_ok=True)
        # This screenshot is diagnostic only; decisions always use the new frame.
        now=time.monotonic()
        if observed['errors'] or classify(observed['report'])=='settlement' or now-self._last_diagnostic >= 2:
            cv2.imencode('.png',image)[1].tofile(path/'latest.png')
            self._last_diagnostic=now
            data = {**observed, 'report':observed['report'].to_dict()}
            (path/'latest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        with (path/'observations.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps({'timestamp':time.time(),'state':classify(observed['report']),'cards':observed['cards'],'errors':observed['errors'],'timings_ms':observed['report'].timings_ms},ensure_ascii=False)+'\n')
        return observed
