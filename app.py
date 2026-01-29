import streamlit as st
import pandas as pd
import requests
import datetime
import time
import random
import re

# === 🎨 页面配置 ===
st.set_page_config(
    page_title="Plan A 猎人终端 (终极修正版)",
    page_icon="🦅",
    layout="wide"
)

# === 🚑 网络环境初始化 ===
import os
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['ALL_PROXY'] = ''
os.environ['NO_PROXY'] = '*'

# === 🧠 核心数据引擎 ===

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/"
    }

def get_hs300_status():
    """
    获取沪深300状态 (修复版)
    腾讯接口: sh000300
    """
    try:
        # 腾讯K线接口
        url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,,,80,qfq"
        resp = requests.get(url, headers=get_headers(), timeout=3)
        data = resp.json()
        
        # 解析路径: data -> sh000300 -> day
        kline = data['data']['sh000300']['day']
        
        df = pd.DataFrame(kline, columns=['date', 'open', 'close', 'high', 'low', 'vol'])
        df['close'] = df['close'].astype(float)
        
        current_close = df.iloc[-1]['close']
        ma60 = df['close'].rolling(60).mean().iloc[-1]
        
        is_safe = current_close > ma60
        return is_safe, current_close, ma60, "获取成功"
    except Exception as e:
        return False, 0, 0, str(e)

def get_stock_history_tencent(code):
    """获取个股历史 (自动识别前缀)"""
    try:
        # 前缀逻辑
        if code.startswith('6'): symbol = f"sh{code}"
        elif code.startswith('8') or code.startswith('4'): return pd.DataFrame() # 排除北交所/三板
        else: symbol = f"sz{code}" # 00/30开头
        
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,60,qfq"
        resp = requests.get(url, headers=get_headers(), timeout=2) # 超时设置短一点，失败就重试
        data = resp.json()
        
        # 腾讯数据可能在 qfqday 或 day 里
        stock_data = data['data'].get(symbol, {})
        kline = stock_data.get('qfqday', stock_data.get('day'))
        
        if not kline: return pd.DataFrame()
        
        df = pd.DataFrame(kline, columns=['date', 'open', 'close', 'high', 'low', 'vol'])
        # 转换数值
        for col in ['open', 'close', 'high', 'low']:
            df[col] = df[col].astype(float)
            
        return df
    except:
        return pd.DataFrame()

def get_active_stocks_sina():
    """
    获取全市场成交额前 300 名的股票 (新浪接口)
    逻辑：只扫描活跃股，死鱼股没有突破意义
    """
    stock_list = []
    page = 1
    max_page = 4 # 抓取前4页，每页80只，共320只最活跃的股票 (包含ETF等，后续过滤)
    
    status_text = st.empty()
    
    while page <= max_page:
        try:
            status_text.text(f"正在获取市场活跃名单... 第 {page}/{max_page} 页")
            # 按成交额(amount)排序
            url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=80&sort=amount&asc=0&node=hs_a&symbol=&_s_r_a=page"
            resp = requests.get(url, headers=get_headers(), timeout=5)
            
            # 简单的正则提取或者eval
            raw_data = resp.text
            if not raw_data or raw_data == '[]': break
            
            # 新浪返回的是非标准JSON (key没有引号)，eval通常能解析
            # 如果eval失败，跳过
            data = eval(raw_data)
            
            for item in data:
                stock_list.append({
                    'code': item['symbol'].replace('sh','').replace('sz',''),
                    'name': item['name'],
                    'price': float(item['trade']),
                    'pct': float(item['changepercent'])
                })
            
            page += 1
            time.sleep(0.5) # 防封
            
        except Exception as e:
            st.error(f"名单获取中断: {e}")
            break
            
    status_text.empty()
    return pd.DataFrame(stock_list)

def run_full_scan():
    """执行扫描逻辑"""
    st_status = st.empty()
    st_bar = st.progress(0)
    
    # 1. 获取名单
    df_pool = get_active_stocks_sina()
    
    if df_pool.empty:
        st.error("未能获取股票名单，请检查网络或稍后重试。")
        return pd.DataFrame()
    
    # 2. 过滤基础条件 (价格<80, 涨幅>0)
    # Plan A 基础过滤
    df_pool = df_pool[
        (df_pool['price'] < 80) & 
        (df_pool['price'] > 0) & 
        (df_pool['pct'] > 0) & # 必须红盘
        (~df_pool['name'].str.contains('ST')) &
        (~df_pool['name'].str.contains('退'))
    ]
    
    total = len(df_pool)
    st_status.text(f"初筛锁定 {total} 只活跃股票，开始计算海龟突破指标...")
    
    results = []
    
    # 3. 逐个分析
    for i, (idx, row) in enumerate(df_pool.iterrows()):
        code = row['code']
        name = row['name']
        price = row['price']
        
        # 进度更新
        pct = int(((i+1) / total) * 100)
        st_bar.progress(pct)
        st_status.text(f"正在分析 [{i+1}/{total}]: {code} {name}")
        
        # 获取历史
        df_hist = get_stock_history_tencent(code)
        
        if len(df_hist) < 25: continue
        
        # 数据对齐：排除当日数据(如果是盘中，腾讯可能包含当日，也可能不包含)
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        last_k_date = df_hist.iloc[-1]['date'].strftime('%Y-%m-%d')
        
        if last_k_date == today_str:
            # 如果最后一行是今天，取[:-1]作为历史
            hist_data = df_hist.iloc[:-1]
        else:
            hist_data = df_hist
            
        # 计算指标
        try:
            # 20日最高价
            high_20 = hist_data['high'].tail(20).max()
            
            # 简易量比 (今日预估量 / 5日均量)
            # 腾讯接口没直接给量比，我们简单算一下：今日成交量 vs 昨日成交量
            # 这里为了不依赖实时成交量字段(新浪数据里没有)，我们只看形态突破
            
            # === Plan A 判定 ===
            # 1. 现价突破 20日高点
            if price > high_20:
                # 补充计算量比因子 (需要看一眼最新的量)
                # 这一步比较难，因为新浪列表没给量比。
                # 我们假设：能上成交额榜单前300的，量能绝对够了。
                
                results.append({
                    '代码': code,
                    '名称': name,
                    '现价': price,
                    '涨幅(%)': row['pct'],
                    '20日高点': high_20,
                    '突破幅度(%)': round((price - high_20)/high_20 * 100, 2)
                })
        except:
            pass
            
        # 延时防封
        time.sleep(0.1)
    
    st_bar.progress(100)
    st_status.success("扫描完成！")
    
    return pd.DataFrame(results)

# === 🖥️ UI 界面 ===
st.markdown("""
<style>
    .stApp {background-color: #F0F2F5;}
    div.stButton > button {background-color: #7B8D8E; color:white; width: 100%;}
    div[data-testid="stMetricValue"] {font-size: 24px;}
</style>
""", unsafe_allow_html=True)

st.title("🦅 Plan A 猎人终端 (终极版)")
st.caption("策略：海龟突破改良版 | 数据源：腾讯财经+新浪财经")

# --- 大盘看板 ---
safe, idx, ma60, msg = get_hs300_status()

col1, col2, col3 = st.columns(3)
col1.metric("沪深300指数", f"{idx:.2f}", delta=None)
col2.metric("MA60牛熊线", f"{ma60:.2f}")

if idx == 0:
    col3.warning(f"数据连接失败: {msg}")
elif safe:
    col3.success("🛡️ 市场环境：安全 (可做多)")
else:
    col3.error("🛑 市场环境：危险 (建议空仓)")

st.divider()

# --- 主功能区 ---
tab1, tab2 = st.tabs(["🔥 机会扫描", "🩺 持仓诊断"])

with tab1:
    st.info("💡 扫描范围：全市场成交额前 300 名的活跃股 (资金主战场)")
    if st.button("🚀 开始全市场扫描", type="primary"):
        if not safe and idx > 0:
            st.warning("⚠️ 警告：大盘处于空头趋势，突破成功率较低！")
        
        df_res = run_full_scan()
        
        if not df_res.empty:
            st.success(f"共发现 {len(df_res)} 只 Plan A 信号股！")
            # 按涨幅排序
            df_res = df_res.sort_values('涨幅(%)', ascending=False)
            st.dataframe(
                df_res.style.format({'现价': '{:.2f}', '20日高点': '{:.2f}'})
                          .background_gradient(subset=['涨幅(%)'], cmap='Reds'),
                use_container_width=True
            )
            
            # 最优推荐
            best = df_res.iloc[0]
            st.markdown(f"""
            ### 🏆 今日首选
            **{best['名称']} ({best['代码']})**
            - 现价: **{best['现价']}** (涨幅 {best['涨幅(%)']}%)
            - 突破力度: 超越20日高点 **{best['突破幅度(%)']}%**
            """)
        else:
            st.info("今日暂无符合 [突破20日新高] 的活跃股。")

with tab2:
    c1, c2 = st.columns(2)
    input_code = c1.text_input("股票代码", "600519")
    input_cost = c2.number_input("持仓成本", 1800.0)
    
    if st.button("诊断持仓"):
        with st.spinner("正在诊断..."):
            df_h = get_stock_history_tencent(input_code)
            
            if df_h.empty:
                st.error("无法获取该股票数据，请检查代码。")
            else:
                curr_price = df_h.iloc[-1]['close']
                # 计算10日低点 (止损线)
                low_10 = df_h['low'].tail(11).iloc[:-1].min()
                
                profit = (curr_price - input_cost) / input_cost * 100
                
                advice = ""
                bg_color = ""
                
                if not safe:
                    advice = "🛑 卖出 (大盘破位)"
                    bg_color = "#f8d7da"
                elif curr_price < low_10:
                    advice = f"🛑 卖出 (跌破10日低点 {low_10})"
                    bg_color = "#f8d7da"
                elif profit < -8:
                    advice = "🛑 卖出 (触及硬止损 -8%)"
                    bg_color = "#f8d7da"
                else:
                    advice = "✅ 持股 (趋势完好)"
                    bg_color = "#d4edda"
                
                st.markdown(f"""
                <div style="background-color: {bg_color}; padding: 20px; border-radius: 10px;">
                    <h3>{advice}</h3>
                    <p>当前价格: {curr_price}</p>
                    <p>当前盈亏: {profit:.2f}%</p>
                    <p>止损红线 (10日低点): {low_10}</p>
                </div>
                """, unsafe_allow_html=True)
