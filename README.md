# Site agregador de ranchos

Site para turistas encontrarem ranchos para alugar, com contato direto com o dono pelo WhatsApp.

**Para o turista:** lista com filtros (pessoas, preço, beira-rio, piscina, rampa, pesca, pet…), página de cada rancho com galeria, preços, regras e botão de WhatsApp, além de uma seção com dicas contra golpes.

**Para você (painel em `/admin`):** cadastro de ranchos e fotos, botões de destaque/verificado/oculto, pedidos de donos que querem anunciar e um relatório mensal por rancho com mensagem pronta para mandar ao dono ("seu rancho teve 37 contatos este mês").

**Para o Google:** títulos e descrições por página, `sitemap.xml`, `robots.txt`, dados estruturados (schema.org) e prévia com foto quando o link é compartilhado no WhatsApp.

---

## Colocar no ar (Render + banco grátis no Neon)

As fotos ficam salvas no banco de dados, então nada se perde quando o Render reinicia ou faz deploy.

### 1. Criar o banco (grátis)

1. Crie uma conta em **neon.tech** e um projeto novo (região São Paulo, se tiver).
2. Copie a **connection string** (começa com `postgresql://...`). Esse é o seu `DATABASE_URL`.

> Por que não o Postgres do Render? O plano gratuito de banco do Render é temporário. O do Neon fica de graça por tempo indeterminado e 0,5 GB cabe milhares de fotos.

### 2. Subir o código

Crie um repositório no GitHub e envie esta pasta:

```bash
git init
git add .
git commit -m "Site de ranchos"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/ranchos.git
git push -u origin main
```

### 3. Criar o serviço no Render

**New → Web Service →** escolha o repositório.

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`

Em **Environment**, adicione:

| Nome | Valor |
|---|---|
| `SITE_NAME` | Nome do site, ex.: `Ranchos da Represa` |
| `CITY_NAME` | Nome da sua cidade |
| `ADMIN_PASSWORD` | Senha do painel (forte!) |
| `SECRET_KEY` | Um texto aleatório longo (pode gerar com `python -c "import secrets;print(secrets.token_hex(32))"`) |
| `DATABASE_URL` | A connection string do Neon |
| `BASE_URL` | O endereço final do site, ex.: `https://ranchosdarepresa.com.br` |
| `SITE_WHATSAPP` | Seu WhatsApp com DDD, para pedidos de cozinheira/faxina (opcional) |

Faça o deploy. As tabelas do banco são criadas sozinhas na primeira vez.

**Plano:** o plano gratuito do Render "dorme" depois de um tempo sem visitas, e a primeira visita demora quase um minuto para carregar. Para um site que recebe turistas do Google, vale usar o plano pago mais barato quando começar a divulgar.

### 4. Domínio próprio (recomendado)

Registre um domínio `.com.br` no **registro.br** (cerca de R$ 40 por ano), de preferência com o nome da cidade, e conecte em **Render → Settings → Custom Domains**. Depois atualize o `BASE_URL`.

### 5. Aparecer no Google

1. Entre no **Google Search Console** e adicione seu domínio.
2. Em **Sitemaps**, envie `https://seudominio.com.br/sitemap.xml`.
3. Crie também um **Perfil da Empresa no Google** para o site.

---

## Usando o painel

Acesse `https://seudominio.com.br/admin` e entre com a senha.

- **Novo rancho:** preencha os dados e escolha as fotos (pode selecionar várias de uma vez). As fotos são redimensionadas e comprimidas automaticamente. A primeira vira capa, e você pode reordenar depois.
- **Verificado:** marque só depois de visitar o rancho e confirmar quem é o dono. Esse selo é o seu diferencial contra golpes.
- **Destaque:** coloca o rancho no topo da lista. É o que você pode cobrar dos donos.
- **Relatório:** mostra visitas e cliques no WhatsApp dos últimos 6 meses, com uma mensagem pronta e um botão para enviar direto ao dono.
- **Donos que querem anunciar:** pedidos que chegam pela página "Anuncie seu rancho", com botão para chamar no WhatsApp.

O número do dono nunca aparece no site: o botão passa pelo site antes de abrir o WhatsApp, e é assim que os contatos são contados. Visitas de robôs e as suas (logado no painel) não entram na conta.

---

## Rodar no computador

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export ADMIN_PASSWORD=teste123     # Windows (PowerShell): $env:ADMIN_PASSWORD="teste123"
export CITY_NAME="Sua Cidade"

flask --app app seed-demo          # opcional: cria 4 ranchos de exemplo com fotos fictícias
flask --app app run --debug
```

Abra http://127.0.0.1:5000. Sem `DATABASE_URL`, o site usa um arquivo SQLite local (`instance/ranchos.db`).

## Arquivos

- `app.py`: rotas, banco de dados, painel e contagem de cliques
- `templates/`: páginas do site e do painel
- `static/style.css`: visual (cores no topo do arquivo)
- `static/app.js`: filtros, galeria de fotos e botões do painel
