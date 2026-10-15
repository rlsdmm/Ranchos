"""Página "Pesca em Miguelópolis": peixes da represa, regras da piracema e licença.

Lista de peixes passada pelo dono do site (o que ele já viu e pescou aqui). As regras resumem a
IN IBAMA nº 25/2009 (defeso da bacia do rio Paraná, que inclui o Rio Grande e as represas).
Fotos do Wikimedia Commons, com autor e licença em CREDITO; troque pelas fotos daqui quando tiver.
"""

REGRAS_CONFERIDAS = "outubro de 2026"
FONTE_DEFESO = ("https://www.gov.br/ibama/pt-br/assuntos/biodiversidade/biodiversidade-aquatica/arquivos/"
                "defesos-continentais/2025-01-20_bacia_hidrografica_do_rio_parana_in_ibama_n-o-25_2009.pdf")
LICENCA_URL = "https://www.gov.br/pt-br/servicos/solicitar-licenca-de-pescador-amador-ou-esportivoo"

# nativa: True = proibida na piracema; False = não nativa citada na IN 25/2009 (liberada na represa,
# com cota); None = não está na lista da norma, então na piracema a orientação é soltar.
PEIXES = [
    dict(key="tucunare", nome="Tucunaré", outros="amarelo, azul e outras variações", cientifico="Cichla spp.",
         nativa=False,
         sobre="O peixe mais procurado da represa pela pesca esportiva. Tem uma mancha redonda perto do rabo, "
               "o \"olho\", e briga forte, com saltos fora d'água. Aqui aparecem várias variações, como o "
               "amarelo e o azul.",
         dica="Iscas artificiais de superfície e meia-água perto de galhadas, pedras e pontas de ilha, "
              "de manhã cedo e no fim da tarde. Gosta de água quente: os meses de calor costumam render mais."),
    dict(key="corvina", nome="Corvina", outros="pescada-do-piauí", cientifico="Plagioscion squamosissimus",
         nativa=False,
         sobre="Prateada, de corpo alongado e boca grande. Anda em cardume nas partes mais fundas: "
               "onde sai uma, costuma sair outras.",
         dica="Isca no fundo ou jig nos canais e áreas fundas da represa. O fim da tarde e a noite "
              "costumam ser bons horários."),
    dict(key="oscar", nome="Oscar", outros="apaiari", cientifico="Astronotus ocellatus", nativa=False,
         sobre="Corpo alto e arredondado, escuro com manchas alaranjadas e um \"olho\" no rabo, parecido com o "
               "do tucunaré. Fica em água parada, perto da vegetação da margem.",
         dica="Minhoca, massa e iscas pequenas perto do capim e dos galhos da margem. Bom peixe para "
              "criança pegar."),
    dict(key="tilapia", nome="Tilápia", outros="", cientifico="Oreochromis spp.", nativa=False,
         sobre="Corpo alto e achatado, acinzentado, com listras verticais fracas e a nadadeira das costas cheia "
               "de espinhos. Muito comum na represa e ótima para fritar.",
         dica="Massa, milho ou minhoca com anzol pequeno, perto da margem e das áreas com capim. "
              "Belisca bastante: fisgue rápido."),
    dict(key="traira", nome="Traíra", outros="", cientifico="Hoplias spp.", nativa=True,
         sobre="Corpo roliço e boca grande, cheia de dentes. Vive em água rasa e parada, no meio do mato "
               "da margem, e ataca com força.",
         dica="Iscas de superfície perto da vegetação e da margem. Use alicate para tirar o anzol: "
              "os dentes cortam."),
    dict(key="piau", nome="Piau", outros="piau-três-pintas e parentes", cientifico="Leporinus spp.",
         nativa=True,
         sobre="Corpo alongado, com manchas pretas nas laterais e boca pequena. Desconfiado, belisca a isca "
               "antes de pegar.",
         dica="Massa ou milho no fundo, com anzol pequeno e paciência. Ceva ajuda a juntar o cardume."),
    dict(key="curimbata", nome="Curimbatá", outros="curimba", cientifico="Prochilodus lineatus", nativa=True,
         sobre="Prateado, de escamas grandes e boca em forma de ventosa, que usa para raspar o lodo do fundo. "
               "É um dos peixes que sobem o rio para desovar na piracema.",
         dica="Como se alimenta de lodo, pega pouco no anzol. Às vezes sai com massa no fundo."),
    dict(key="piranha-amarela", nome="Piranha-amarela", outros="", cientifico="Serrasalmus maculatus",
         nativa=True,
         sobre="Corpo alto, amarelado com pintinhas escuras, e dentes bem afiados.",
         dica="Pega fácil com pedaço de carne ou de peixe. Use empate de aço e alicate, e cuidado com "
              "os dedos."),
    dict(key="jacunda", nome="Jacundá", outros="", cientifico="Crenicichla spp.", nativa=True,
         sobre="Peixe comprido, de boca grande, que fica escondido entre pedras, galhos e vegetação e ataca "
               "de tocaia.",
         dica="Iscas artificiais pequenas e minhoca perto da margem, nas pedras e na galhada."),
    dict(key="pacu-prata", nome="Pacu-prata", outros="", cientifico="Metynnis spp.", nativa=None,
         sobre="Pequeno, redondo e bem prateado, parecido com uma moeda. Anda em cardume.",
         dica="Massa, milho ou pedacinho de fruta, com anzol pequeno."),
    dict(key="camarao", nome="Camarão de água doce", outros="", cientifico="Macrobrachium sp.", nativa=None,
         sobre="Camarão pequeno e quase transparente que vive na margem, no meio da vegetação. "
               "Muita gente usa como isca.",
         dica="Fora da piracema é uma ótima isca para corvina e outros peixes. Na piracema, a lei proíbe "
              "usar camarão como isca."),
]
PEIXE = {p["key"]: p for p in PEIXES}

# Fotos do Wikimedia Commons (static/peixes/<key>.webp)
CREDITO = {
    "tucunare": ("Karelj", "domínio público", "https://commons.wikimedia.org/wiki/File:Cichla_ocellaris_Dvur_zoo_2.jpg"),
    "corvina": ("François-Louis Laporte, conde de Castelnau (ilustração)", "domínio público",
                "https://commons.wikimedia.org/wiki/File:Plagioscion_squamosissimus.jpg"),
    "oscar": ("George Chernilevsky", "domínio público",
              "https://commons.wikimedia.org/wiki/File:Astronotus_ocellatus_2015_G1.jpg"),
    "tilapia": ("Bjørn Christian Tørrissen", "CC BY-SA 3.0",
                "https://commons.wikimedia.org/wiki/File:Oreochromis-niloticus-Nairobi.JPG"),
    "traira": ("Enrique Manuel González González", "CC BY-SA 4.0",
               "https://commons.wikimedia.org/wiki/File:Tararira_(Hoplias_malabaricus),_Uruguay,_2020.jpg"),
    "piau": ("Gerry van Tonder", "CC BY 4.0", "https://commons.wikimedia.org/wiki/File:Leporinus_friderici_60892985.jpg"),
    "curimbata": ("dariocrosa", "CC0",
                  "https://commons.wikimedia.org/wiki/File:Prochilodus_lineatus_351939209_(cropped).jpg"),
    "piranha-amarela": ("Kozue Kawakami", "CC BY-SA 4.0",
                        "https://commons.wikimedia.org/wiki/File:Serrasalmus_maculatus_123115950.jpg"),
    "jacunda": ("Clinton & Charles Robertson", "CC BY 2.0", "https://commons.wikimedia.org/wiki/File:Crenicichla_lenticulata.jpg"),
    "pacu-prata": ("Sortius", "CC BY-SA 4.0",
                   "https://commons.wikimedia.org/wiki/File:Metynnis_lippincottianus_-_Spotted_Silver_Dollar.jpg"),
    "camarao": ("Jonathan Vera Caripe", "CC BY 2.0",
                "https://commons.wikimedia.org/wiki/File:Macrobrachium_amazonicum_(Heller,_1862).jpg"),
}
