
# Streamlit App: Arbitrage Finder with User Input Keywords

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import io

# --- Scraper for eBay ---
def search_ebay(keyword):
    url = f"https://www.ebay.com/sch/i.html?_nkw={keyword.replace(' ', '+')}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    prices = []
    for item in soup.select('.s-item'):
        price_tag = item.select_one('.s-item__price')
        if price_tag:
            try:
                price = float(price_tag.text.replace('$','').replace(',','').split(' ')[0])
                prices.append(price)
            except:
                continue
    return prices

# --- Scraper for Amazon ---
def search_amazon(keyword):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    prices = []
    for item in soup.select('div.s-main-slot div[data-component-type="s-search-result"]'):
        price_tag = item.select_one('span.a-price > span.a-offscreen')
        if price_tag:
            try:
                price = float(price_tag.text.replace('$','').replace(',',''))
                prices.append(price)
            except:
                continue
    return prices

# --- Arbitrage Logic ---
def find_arbitrage(keywords):
    alerts = []
    for keyword in keywords:
        ebay_prices = search_ebay(keyword)
        amazon_prices = search_amazon(keyword)

        if ebay_prices and amazon_prices:
            min_ebay = min(ebay_prices)
            max_amazon = max(amazon_prices)
            profit_margin = max_amazon - min_ebay

            if profit_margin > 10:
                alerts.append({
                    'Date': datetime.datetime.now().strftime('%Y-%m-%d'),
                    'Keyword': keyword,
                    'Min eBay Price': min_ebay,
                    'Max Amazon Price': max_amazon,
                    'Profit Margin': round(profit_margin, 2)
                })
    return alerts

# --- Streamlit Interface ---
st.set_page_config(page_title="Arbitrage Finder", layout="centered")
st.title("🛍️ Custom Keyword Arbitrage Opportunities")

user_input = st.text_area("Enter product keywords (comma-separated):", "portable blender, LED mask, mini projector")
run_button = st.button("🔍 Run Analysis")

if run_button:
    keywords = [kw.strip() for kw in user_input.split(',') if kw.strip()]
    if not keywords:
        st.warning("Please enter at least one keyword.")
    else:
        with st.spinner("Scanning keywords across Amazon and eBay..."):
            results = find_arbitrage(keywords)
            if results:
                df = pd.DataFrame(results)
                st.success(f"Found {len(df)} arbitrage opportunities!")
                st.dataframe(df)

                output = io.BytesIO()
                df.to_excel(output, index=False, engine='openpyxl')
                output.seek(0)

                st.download_button(
                    label="📥 Download Excel File",
                    data=output,
                    file_name="arbitrage_opportunities.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("No arbitrage opportunities found for the entered keywords.")
