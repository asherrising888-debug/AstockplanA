import streamlit as st
import akshare as ak
import pandas as pd
import datetime
import time
import random  # 引入随机数，模拟人类操作的不确定性

# === 🎨 页面配置 ===
st.set_page_config(
    page_title="Plan A 猎人终端",
    page_icon="🦅",
    layout="wide"
)

# === 🚑 网络配置 ===
import os
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['ALL_PROXY'] = ''
os.environ['NO_PROXY'] = '*'

# === 🧠 核心功能 ===

@st.cache_data(ttl=600)
def check_market_status():
    """检查大盘 (带重试)"""
    for _ in range(3):
        try:
            df_index = ak.stock_zh_index_daily_em(symbol="sh000300")
            df_index = df_index.sort_values('date').tail(70)
            current_close = df_index.iloc[-1]['close']
            ma60 = df_index['close'].rolling(60).mean().iloc[-1]
            last_date = str(df_index.iloc[-1]['date'])
            return (current_close > ma60), current_close, ma60, last_date
        except:
            time.sleep(1)
    return False, 0, 0, "获取失败"

def get_stock_history_safe(code):
    """超级稳健的历史K线获取函数"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 随机延时 0.5 ~ 1.5 秒，模拟人类
            time.sleep(random.uniform(0.5, 1.5))
            
            # 获取数据
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
            return df
        except Exception as e:
            # 如果是连接错误，多睡一会儿
            time.sleep(3) 
    return pd.DataFrame()

def run_scanner():
    status_text = st.empty()
    progress_bar = st.progress(0)
    result_area = st.container() # 占位符
    
    try:
        status_text.text("正在连接交易所接口 (云端模式已降速)...")
        
        # 1. 获取全市场实时数据 (这个通常不会挂)
        df_spot = ak.stock_zh_a_spot_em()
        
        # 2. 初筛
        mask = (df_spot['最新价'] < 80) & \
               (df_spot['最新价'] > 0) & \
               (df_spot['量比'] > 1.2) & \
               (df_spot['涨跌幅'] > 0) & \
               (~df_spot['名称'].str.contains('ST|退'))
        
        candidates = df_spot[mask].copy()
        
        # ⚠️ 关键修改：只取 Top 15，防止超时或被封
        candidates = candidates.sort_values('量比', ascending=False).head(15)
        total_scan = len(candidates)
        
        status_text.text(f"初筛命中 {total_scan} 只，正在慢速深度扫描 (防封锁)...")
        
        final_list = []
        
        for i, (idx, row) in enumerate(candidates.iterrows()):
            code = row['代码']
            name = row['名称']
            price = row['最新价']
            
            # 更新进度
            pct = int(((i + 1) / total_scan) * 100)
            progress_bar.progress(pct)
            status_text.text(f"正在分析 [{i+1}/{total_scan}]: {code} {name} ... (请耐心等待)")
            
            # 获取历史数据 (带重试)
            df_hist = get_stock_history_safe(code)
            
            if len(df_hist) < 30: continue
            
            # 数据处理
            last_date_str = str(df_hist.iloc[-1]['日期'])
            today_str = datetime.datetime.now().strftime('%Y-%m-%d')
            
            if last_date_str == today_str:
                hist_data = df_hist.iloc[:-1]
            else:
                hist_data = df_hist
                
            high_20 = hist_data['最高'].tail(20).max()
            
            # Plan A 判定
            if price > high_20:
                final_list.append({
                    '代码': code,
                    '名称': name,
                    '现价': price,
                    '涨幅(%)': row['涨跌幅'],
                    '量比': row['量比'],
                    '20日高点': high_20
                })
        
        progress_bar.progress(100)
        status_text.success("扫描完成！")
        return pd.DataFrame(final_list)
        
    except Exception as e:
        st.error(f"扫描中断: {e}")
        # 即使报错，如果已经扫描到一部分，也返回
        if 'final_list' in locals() and final_list:
            return pd.DataFrame(final_list)
        return pd.DataFrame()

def check_portfolio(code, cost, market_safe):
    try:
        df_spot = ak.stock_zh_a_spot_em()
        row = df_spot[df_spot['代码'] == code]
        if row.empty: return None, "代码错误或停牌"
        
        price = row.iloc[0]['最新价']
        name = row.iloc[0]['名称']
        
        df_hist = get_stock_history_safe(code)
        if df_hist.empty: return None, "无法获取历史数据(连接超时)"
        
        low_10 = df_hist['最低'].tail(11).iloc[:-1].min()
        profit_pct = (price - cost) / cost * 100
        
        advice = "✅ 持股待涨"
        bg_color = "#d4edda"
        
        if not market_safe:
            advice = "🛑 建议卖出 (大盘破位)"
            bg_color = "#f8d7da"
        elif price < low_10:
            advice = f"🛑 建议卖出 (跌破10日低点 {low_10})"
            bg_color = "#f8d7da"
        elif profit_pct < -8:
            advice = "🛑 建议卖出 (触及硬止损 -8%)"
            bg_color = "#f8d7da"
            
        return {'name': name, 'price': price, 'low_10': low_10, 'profit': profit_pct, 'advice': advice, 'bg_color': bg_color}, None
    except Exception as e:
        return None, str(e)

# === UI 布局 ===
st.markdown("""
<style>
    .stApp {background-color: #F0F2F5;}
    div.stButton > button:first-child {background-color: #7B8D8E; color: white;}
</style>
""", unsafe_allow_html=True)

st.title("🦅 Plan A 猎人终端 (云端稳健版)")

# 大盘
is_safe, idx_val, ma60_val, idx_date = check_market_status()
c1, c2, c3 = st.columns(3)
c1.metric("沪深300", f"{idx_val:.2f}")
c2.metric("MA60生命线", f"{ma60_val:.2f}")
if is_safe:
    c3.success("🛡️ 环境安全")
else:
    c3.error("🛑 环境危险")

st.divider()

tab1, tab2 = st.tabs(["🔥 机会扫描", "🩺 持仓诊断"])

with tab1:
    st.info("提示：为防止云端IP被封，扫描速度已限制。仅扫描全市场量比前 15 名。")
    if st.button("🚀 开始扫描"):
        with st.spinner('连接数据源中...'):
            df_res = run_scanner()
        
        if not df_res.empty:
            st.dataframe(df_res.style.background_gradient(subset=['量比'], cmap='Blues'), use_container_width=True)
            best = df_res.iloc[0]
            st.success(f"🔥 首选推荐: {best['名称']} ({best['代码']}) - 量比 {best['量比']}")
        else:
            st.warning("未扫描到结果 (或网络请求被拦截，请稍后再试)")

with tab2:
    c1, c2 = st.columns(2)
    code = c1.text_input("代码", "600519")
    cost = c2.number_input("成本", 1800.0)
    if st.button("诊断"):
        with st.spinner('分析中...'):
            res, err = check_portfolio(code, cost, is_safe)
        if err: st.error(err)
        else:
            st.markdown(f"""
            <div style="background-color: {res['bg_color']}; padding: 15px; border-radius: 10px;">
                <b>{res['name']}</b> | 现价: {res['price']} | 盈亏: {res['profit']:.2f}%<br>
                止损位: {res['low_10']}<br>
                <h3>{res['advice']}</h3>
            </div>
            """, unsafe_allow_html=True)
