import streamlit as st
import pandas as pd
import requests
import datetime
import time
import random

# === 🎨 页面配置 ===
st.set_page_config(
    page_title="Plan A 猎人终端 (腾讯源)",
    page_icon="🦅",
    layout="wide"
)

# === 🧠 腾讯财经数据引擎 (Tencent Engine) ===

def get_headers():
    """伪装浏览器头"""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "http://finance.qq.com/"
    }

def get_stock_history_tencent(code):
    """
    从腾讯获取历史K线 (前复权)
    接口: http://web.ifzq.gtimg.cn/appstock/app/fqkline/get
    """
    try:
        # 处理代码前缀 sh/sz
        symbol = f"sh{code}" if code.startswith('6') else f"sz{code}"
        
        # 获取最近 60 天数据
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,60,qfq"
        
        resp = requests.get(url, headers=get_headers(), timeout=5)
        data = resp.json()
        
        # 解析 JSON
        # 路径: data -> code -> qfqday (前复权) 或 day (如果不复权)
        # 腾讯有时候没有 qfqday 字段，说明没有分红，直接用 day
        kline_data = data['data'][symbol].get('qfqday', data['data'][symbol].get('day'))
        
        if not kline_data: return pd.DataFrame()
        
        # 转换为 DataFrame
        # 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
        df = pd.DataFrame(kline_data, columns=['date', 'open', 'close', 'high', 'low', 'vol'])
        df['date'] = pd.to_datetime(df['date'])
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        
        return df
        
    except Exception as e:
        # print(f"历史获取失败: {e}")
        return pd.DataFrame()

def get_realtime_batch_tencent(code_list):
    """
    批量获取实时行情 (腾讯极速接口)
    接口: http://qt.gtimg.cn/q=sh600519,sz000001...
    """
    try:
        # 加上前缀
        symbols = []
        for c in code_list:
            if c.startswith('6'): symbols.append(f"sh{c}")
            else: symbols.append(f"sz{c}")
            
        # 拼接 URL
        codes_str = ",".join(symbols)
        url = f"http://qt.gtimg.cn/q={codes_str}"
        
        resp = requests.get(url, headers=get_headers(), timeout=5)
        
        # 解析返回的文本
        # 格式: v_sh600519="1:名字~2:代码~3:当前价~4:昨收~...~30:时间~..."
        results = []
        lines = resp.text.split(';')
        
        for line in lines:
            if len(line) < 10: continue
            content = line.split('"')[1]
            data = content.split('~')
            
            if len(data) < 30: continue
            
            # 提取关键字段
            name = data[1]
            code = data[2]
            price = float(data[3])
            last_close = float(data[4])
            
            # 计算涨幅
            pct_chg = 0
            if last_close > 0:
                pct_chg = (price - last_close) / last_close * 100
                
            # 简单的量比估算 (腾讯接口直接量比数据不准，这里用简化逻辑)
            # 或者我们依赖历史数据计算量比，这里先只取涨幅
            
            results.append({
                'code': code,
                'name': name,
                'price': price,
                'pct': pct_chg,
                'vol_str': data[6] # 成交量(手)
            })
            
        return pd.DataFrame(results)
        
    except Exception as e:
        return pd.DataFrame()

def get_market_rank_sina():
    """
    获取全市场涨幅榜/量比榜 (利用新浪网页接口，作为初筛池)
    因为腾讯没有直接的全市场排行接口，新浪的 html 接口更开放
    """
    try:
        # 这里为了演示稳定，我们手动定义一些热门股或者沪深300成分股作为扫描池
        # 真实全市场扫描需要爬取多页，云端容易超时
        # 策略：我们扫描【近期热门】和【沪深300】
        
        # 这里我们用一个简化的 Trick：
        # 直接扫描 沪深300 权重股 + 一些热门代码
        # 为了演示效果，我内置一个常用的观察池 (实际可以用 requests 爬取 sina vip 接口)
        
        # 既然要求全市场，我们用 requests 爬取新浪行情的 json
        # 获取沪深A股涨幅榜前 80 名 (作为活跃股代表)
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=80&sort=changepercent&asc=0&node=hs_a&symbol=&_s_r_a=page"
        
        resp = requests.get(url, headers=get_headers(), timeout=5)
        data = eval(resp.text) # 新浪返回的是 JS 对象格式
        
        code_list = [x['symbol'].replace('sh','').replace('sz','') for x in data]
        return code_list
        
    except:
        # 如果爬取失败，返回一个保底列表 (茅台等龙头)
        return ['600519','300750','601318','000858','002594','600036','601012','000001']

# === 🧠 策略逻辑整合 ===

@st.cache_data(ttl=300)
def check_market_status():
    """检查大盘 (MA60)"""
    try:
        # 获取沪深300历史
        df = get_stock_history_tencent('000300') # 000300 在腾讯是 sh000300
        if df.empty: return False, 0, 0
        
        curr = df.iloc[-1]['close']
        ma60 = df['close'].rolling(60).mean().iloc[-1]
        return curr > ma60, curr, ma60
    except:
        return False, 0, 0

def run_scanner_tencent():
    st_status = st.empty()
    st_bar = st.progress(0)
    
    st_status.text("正在从新浪获取活跃股名单...")
    
    # 1. 获取候选池 (活跃股)
    codes = get_market_rank_sina()
    total = len(codes)
    
    st_status.text(f"锁定 {total} 只活跃股票，开始腾讯接口深度扫描...")
    
    # 2. 批量获取实时行情 (腾讯支持一次请求多只)
    # 分批请求，每批 20 只
    batch_size = 20
    realtime_data = []
    
    for i in range(0, total, batch_size):
        batch_codes = codes[i:i+batch_size]
        df_batch = get_realtime_batch_tencent(batch_codes)
        if not df_batch.empty:
            realtime_data.append(df_batch)
        time.sleep(0.1) # 极短延时即可，腾讯很快
        
    if not realtime_data:
        st.error("无法连接行情服务器")
        return pd.DataFrame()
        
    df_all = pd.concat(realtime_data)
    
    # 3. 逐个分析历史趋势 (Plan A 逻辑)
    final_list = []
    
    # 初筛: 涨幅 > 0 (只看红盘)
    candidates = df_all[df_all['pct'] > 0]
    total_scan = len(candidates)
    
    for i, (idx, row) in enumerate(candidates.iterrows()):
        code = row['code']
        name = row['name']
        price = row['price']
        
        pct = int(((i+1) / total_scan) * 100)
        st_bar.progress(pct)
        st_status.text(f"正在分析趋势: {code} {name} ...")
        
        # 获取历史
        df_hist = get_stock_history_tencent(code)
        if len(df_hist) < 30: continue
        
        # 计算20日新高
        # 排除今天 (如果是盘中，最后一行可能是今天，需要判断日期)
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        last_hist_date = df_hist.iloc[-1]['date'].strftime('%Y-%m-%d')
        
        if last_hist_date == today_str:
            hist_subset = df_hist.iloc[:-1]
        else:
            hist_subset = df_hist
            
        high_20 = hist_subset['high'].tail(20).max()
        
        # Plan A: 突破
        if price > high_20:
            # 计算简易量比 (今天预估量 / 5日均量)
            try:
                vol_ma5 = hist_subset['vol'].tail(5).mean()
                # 腾讯返回的 vol 是手，不需要转换
                # 简单估算：当前量 / (240分钟 * 进度) -> 全天预估
                # 这里为了简单，直接对比昨天量
                last_vol = hist_subset.iloc[-1]['vol']
                # 既然是突破，我们简单要求 涨幅>2% 且 价格>20日高
                if row['pct'] > 2.0:
                    final_list.append({
                        '代码': code,
                        '名称': name,
                        '现价': price,
                        '涨幅(%)': f"{row['pct']:.2f}",
                        '20日高点': high_20
                    })
            except: pass
            
    st_bar.progress(100)
    st_status.success("扫描完成")
    return pd.DataFrame(final_list)

def check_portfolio_tencent(code, cost, market_safe):
    try:
        # 实时
        df_rt = get_realtime_batch_tencent([code])
        if df_rt.empty: return None, "代码错误"
        
        price = df_rt.iloc[0]['price']
        name = df_rt.iloc[0]['name']
        
        # 历史
        df_hist = get_stock_history_tencent(code)
        if df_hist.empty: return None, "无历史数据"
        
        low_10 = df_hist['low'].tail(11).iloc[:-1].min()
        profit = (price - cost) / cost * 100
        
        advice = "✅ 持股待涨"
        bg = "#d4edda"
        
        if not market_safe:
            advice = "🛑 卖出 (大盘破位)"
            bg = "#f8d7da"
        elif price < low_10:
            advice = f"🛑 卖出 (跌破10日低点 {low_10})"
            bg = "#f8d7da"
        elif profit < -8:
            advice = "🛑 卖出 (止损 -8%)"
            bg = "#f8d7da"
            
        return {'name':name, 'price':price, 'profit':profit, 'low_10':low_10, 'advice':advice, 'bg':bg}, None
    except Exception as e:
        return None, str(e)

# === 🖥️ UI ===
st.markdown("""<style>.stApp {background-color: #F0F2F5;} div.stButton > button {background-color: #7B8D8E; color:white;}</style>""", unsafe_allow_html=True)

st.title("🦅 Plan A 猎人终端 (腾讯极速版)")

safe, idx, ma60 = check_market_status()
c1, c2, c3 = st.columns(3)
c1.metric("沪深300", f"{idx:.2f}")
c2.metric("MA60生命线", f"{ma60:.2f}")
if safe: c3.success("🛡️ 环境安全")
else: c3.error("🛑 环境危险")

tab1, tab2 = st.tabs(["🔥 扫描", "🩺 诊断"])

with tab1:
    st.info("数据源：腾讯财经 | 逻辑：扫描市场活跃股 -> 筛选突破20日新高")
    if st.button("🚀 开始扫描"):
        res = run_scanner_tencent()
        if not res.empty:
            st.dataframe(res, use_container_width=True)
            st.success(f"发现 {len(res)} 只突破股！")
        else:
            st.warning("暂无符合条件的目标")

with tab2:
    c1, c2 = st.columns(2)
    code = c1.text_input("代码", "600519")
    cost = c2.number_input("成本", 1800.0)
    if st.button("诊断"):
        res, err = check_portfolio_tencent(code, cost, safe)
        if err: st.error(err)
        else:
            st.markdown(f"""
            <div style="background-color: {res['bg']}; padding: 15px; border-radius: 10px;">
            <b>{res['name']}</b> | 现价 {res['price']} | 盈亏 {res['profit']:.2f}%<br>
            止损位: {res['low_10']}<br>
            <h3>{res['advice']}</h3>
            </div>
            """, unsafe_allow_html=True)
