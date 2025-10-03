# app.py
import streamlit as st
from bot import ejecutar_bot

st.title("🚀 Mi Trading Bot 2025")

if st.button("Ejecutar Bot"):
    resultado = ejecutar_bot()
    st.success(resultado)
