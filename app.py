import streamlit as st
import akshare as ak
import pandas as pd
import datetime
import time

# === 🎨 页面配置 ===
st.set_page_config(
    page_title="Plan A 猎人终端",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# === 🚑 网络急救包 (云端也加上，防万一) ===
import os

os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['ALL_PROXY'] = ''
os.environ['NO_PROXY'] = '*'


# === 🧠 核心策略逻辑 ===

# 缓存大盘数据，避免每次刷新都请求，有效期10分钟
@st.cache_data(ttl=600)
def check_market_status():
    """检查沪深300是否站上MA60"""
    try:
        # 获取沪深300
        df_index = ak.stock_zh_index_daily_em(symbol="sh000300")
        df_index = df_index.sort_values('date').tail(70)

        current_close = df_index.iloc[-1]['close']
        last_date = df_index.iloc[-1]['date']

        # 计算MA60
        ma60 = df_index['close'].rolling(60).mean().iloc[-1]

        is_safe = current_close > ma60
        return is_safe, current_close, ma60, last_date
    except Exception as e:
        st.error(f"大盘数据获取失败: {e}")
        return False, 0, 0, ""


# 缓存个股历史数据，防止频繁请求被封
def get_stock_history_safe(code):
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
        return df
    except:
        return pd.DataFrame()


def run_scanner():
    """全市场扫描逻辑"""
    status_text = st.empty()
    progress_bar = st.progress(0)

    try:
        status_text.text("正在连接交易所接口获取实时行情...")
        # 1. 获取全市场实时数据
        df_spot = ak.stock_zh_a_spot_em()

        # 2. 初筛 (快速过滤)
        # 逻辑：价格<80, 量比>1.2, 涨幅>0, 非ST
        mask = (df_spot['最新价'] < 80) & \
               (df_spot['最新价'] > 0) & \
               (df_spot['量比'] > 1.2) & \
               (df_spot['涨跌幅'] > 0) & \
               (~df_spot['名称'].str.contains('ST|退'))

        candidates = df_spot[mask].copy()

        # 为了云端速度，只取量比最大的前 30 只进行深度扫描
        candidates = candidates.sort_values('量比', ascending=False).head(30)
        total_scan = len(candidates)

        status_text.text(f"初筛命中 {total_scan} 只，开始深度技术分析 (Plan A)...")

        final_list = []

        for i, (idx, row) in enumerate(candidates.iterrows()):
            code = row['代码']
            name = row['名称']
            price = row['最新价']

            # 更新进度
            progress = int((i / total_scan) * 100)
            progress_bar.progress(progress)
            status_text.text(f"正在分析 [{i + 1}/{total_scan}]: {code} {name} ...")

            # 礼貌性延时
            time.sleep(0.2)

            # 获取历史数据
            df_hist = get_stock_history_safe(code)
            if len(df_hist) < 30: continue

            # 处理数据，不包含当天
            last_date_str = str(df_hist.iloc[-1]['日期'])
            today_str = datetime.datetime.now().strftime('%Y-%m-%d')

            if last_date_str == today_str:
                hist_data = df_hist.iloc[:-1]
            else:
                hist_data = df_hist

            # 计算20日新高
            high_20 = hist_data['最高'].tail(20).max()

            # === Plan A 核心判定 ===
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
        status_text.text("扫描完成！")
        return pd.DataFrame(final_list)

    except Exception as e:
        st.error(f"扫描出错: {e}")
        return pd.DataFrame()


def check_portfolio(code, cost, market_safe):
    """持仓诊断逻辑"""
    try:
        # 获取实时数据
        df_spot = ak.stock_zh_a_spot_em()
        row = df_spot[df_spot['代码'] == code]

        if row.empty:
            return None, "代码错误或停牌"

        price = row.iloc[0]['最新价']
        name = row.iloc[0]['名称']

        # 获取历史算止损
        df_hist = get_stock_history_safe(code)
        if df_hist.empty: return None, "无法获取历史数据"

        low_10 = df_hist['最低'].tail(11).iloc[:-1].min()

        profit_pct = (price - cost) / cost * 100

        # 诊断逻辑
        advice = "✅ 持股待涨 (符合趋势)"
        bg_color = "#d4edda"  # 浅绿

        if not market_safe:
            advice = "🛑 建议卖出 (大盘破位)"
            bg_color = "#f8d7da"  # 浅红
        elif price < low_10:
            advice = f"🛑 建议卖出 (跌破10日低点 {low_10})"
            bg_color = "#f8d7da"
        elif profit_pct < -8:
            advice = "🛑 建议卖出 (触及硬止损 -8%)"
            bg_color = "#f8d7da"

        return {
            'name': name,
            'price': price,
            'low_10': low_10,
            'profit': profit_pct,
            'advice': advice,
            'bg_color': bg_color
        }, None

    except Exception as e:
        return None, str(e)


# === 🖥️ UI 界面 ===

# 注入一点莫兰迪风格 CSS
st.markdown("""
<style>
    .stApp {
        background-color: #F0F2F5;
    }
    div.stButton > button:first-child {
        background-color: #7B8D8E;
        color: white;
        border-radius: 5px;
        border: none;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("🦅 Plan A A股猎人终端")
st.markdown("##### 海龟突破改良版 | 实时全市场监控")

# --- 1. 大盘看板 ---
is_safe, idx_val, ma60_val, idx_date = check_market_status()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("沪深300指数", f"{idx_val:.2f}")
with col2:
    st.metric("MA60生命线", f"{ma60_val:.2f}")
with col3:
    if is_safe:
        st.success(f"🛡️ 市场环境: 安全 (可做多)\n日期: {idx_date}")
    else:
        st.error(f"🛑 市场环境: 危险 (空仓)\n日期: {idx_date}")

st.divider()

# --- 2. 功能分区 ---
tab1, tab2 = st.tabs(["🔥 机会扫描 (Scanner)", "🩺 持仓诊断 (Doctor)"])

# === Tab 1: 扫描器 ===
with tab1:
    st.info("策略逻辑：价格突破20日新高 + 量比>1.2 + 价格<80 + 大盘安全")

    if st.button("🚀 开始全市场扫描", type="primary"):
        if not is_safe:
            st.warning("⚠️ 警告：当前大盘跌破生命线，建议管住手！")

        with st.spinner('正在连接东方财富数据源...'):
            df_res = run_scanner()

        if not df_res.empty:
            st.success(f"发现 {len(df_res)} 只符合 Plan A 的股票！")

            # 格式化显示
            st.dataframe(
                df_res.style.background_gradient(subset=['量比'], cmap='Blues'),
                use_container_width=True,
                height=400
            )

            # 最优推荐
            best = df_res.iloc[0]
            st.markdown(f"""
            ### 🔥 今日最强推荐
            **{best['名称']} ({best['代码']})**
            - 现价: **{best['现价']}**
            - 量比: **{best['量比']}** (资金流入明显)
            - 20日高点: {best['20日高点']}
            """)
        else:
            st.info("今日暂无符合条件的股票，休息一下吧🍵")

# === Tab 2: 诊断器 ===
with tab2:
    c1, c2 = st.columns(2)
    with c1:
        input_code = st.text_input("股票代码", value="600519")
    with c2:
        input_cost = st.number_input("持仓成本", value=1800.0)

    if st.button("🔍 诊断持仓"):
        res, err = check_portfolio(input_code, input_cost, is_safe)

        if err:
            st.error(f"诊断失败: {err}")
        else:
            # 使用卡片展示结果
            st.markdown(f"""
            <div style="background-color: {res['bg_color']}; padding: 20px; border-radius: 10px; border: 1px solid #ddd;">
                <h3 style="margin:0; color: #333;">{res['name']} ({input_code})</h3>
                <hr>
                <p><b>当前价格:</b> {res['price']}</p>
                <p><b>当前盈亏:</b> {res['profit']:.2f}%</p>
                <p><b>10日低点 (止损位):</b> {res['low_10']}</p>
                <hr>
                <h4 style="margin:0;">{res['advice']}</h4>
            </div>
            """, unsafe_allow_html=True)

# 底部版权
st.markdown("---")
st.caption("数据来源: Akshare (东方财富) | 策略: Plan A (Trend Following)")