# Streamlit App: Product Arbitrage Finder

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import io

# --- Get trending keywords ---
def get_trending_keywords():
    return ["portable blender", "LED mask", "mini projector", "desk vacuum", "neck fan"]

# --- Scraper for eBay ---
def search_ebay(keyword):
    url = f"https://www.ebay.com/sch/i.html?_nkw={keyword.replace(' ', '+')}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    prices = []
    for item in soup.select('.s-item__price')[:5]:
        try:
            price = float(item.text.replace('$','').replace(',','').split(' ')[0])
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
    for item in soup.select('span.a-price > span.a-offscreen')[:5]:
        try:
            price = float(item.text.replace('$','').replace(',',''))
            prices.append(price)
        except:
            continue
    return prices

# --- Arbitrage Logic ---
def find_arbitrage():
    keywords = get_trending_keywords()
    alerts = []
    for keyword in keywords:
        ebay_prices = search_ebay(keyword)
        amazon_prices = search_amazon(keyword)
        if not ebay_prices or not amazon_prices:
            continue
        min_ebay = min(ebay_prices)
        max_amazon = max(amazon_prices)
        if max_amazon - min_ebay > 10:
            alerts.append({
                'Date': datetime.datetime.now().strftime('%Y-%m-%d'),
                'Keyword': keyword,
                'eBay Price': min_ebay,
                'Amazon Price': max_amazon,
                'Profit Margin': round(max_amazon - min_ebay, 2)
            })
    return alerts

# --- Streamlit Interface ---
st.set_page_config(page_title="Arbitrage Finder", layout="centered")
st.title("🛍️ Product Arbitrage Finder")

if st.button("🔍 Run Arbitrage Check"):
    with st.spinner("Scraping eBay and Amazon..."):
        results = find_arbitrage()
        if results:
            df = pd.DataFrame(results)
            st.success(f"Found {len(df)} opportunities!")
            st.dataframe(df)

            output = io.BytesIO()
            df.to_excel(output, index=False, engine='openpyxl')
            output.seek(0)

            st.download_button(
                label="📥 Download Excel File",
                data=output,
                file_name="arbitrage_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("No arbitrage opportunities found today.")
