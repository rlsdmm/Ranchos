# Lido automaticamente pelo gunicorn (vale junto com o start command do Render).
# O padrão de 30 s é pouco para processar várias fotos de uma vez no plano grátis (0,1 CPU).
timeout = 180
