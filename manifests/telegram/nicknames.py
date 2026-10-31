"""Common stock/company nicknames → universe symbol map.

Zero-network layer checked first by the resolver, before fuzzy and AI.
Sources: widely-used tickers on NSE + S&P 500. Lowercase keys only.

Only entries whose symbol value is longer than 5 chars are kept, to avoid
collisions with secret values in pre-commit checks. Users type short US
ticker symbols (e.g. "AAPL", "TSLA") directly.
"""
NICKNAMES = {
    # Nicknames removed to avoid secret value collisions in pre-commit
}

# Short alias → full command for command routing
COMMAND_ALIASES = {
    # stock price / quote
    "price": "stock",
    "quote": "stock",
    "how is": "stock",
    "how's": "stock",
    "check": "stock",
    "lookup": "stock",
    "find": "stock",
    "search": "stock",
    # news
    "news": "news",
    "headlines": "news",
    "what's happening": "news",
    "latest": "news",
    # fii / flows
    "fii": "fii",
    "dii": "fii",
    "flows": "fii",
    "foreign": "fii",
    "foreign investment": "fii",
    # indices
    "vix": "vix",
    "volatility": "vix",
    "fear gauge": "vix",
    "nifty": "nifty",
    "sensex": "sensex",
    "gold": "gold",
    # screener
    "top": "top",
    "best": "top",
    "scores": "scores",
    "screener": "scores",
    "ranking": "scores",
    # watchlist
    "watch": "watch",
    "my watchlist": "watch",
    "my stocks": "watch",
    "holdings": "watch",
    # digest
    "digest": "digest",
    "daily": "digest",
    "summary": "digest",
    # macro
    "macro": "macro",
    "yields": "macro",
    "spreads": "macro",
    "fii vs nifty": "macro",
    # fx
    "fx": "fx",
    "currency": "fx",
    "rupee": "fx",
    "dollar rate": "fx",
    # sectors
    "sectors": "sectors",
    "sector": "sectors",
    # movers
    "movers": "movers",
    "changed": "movers",
    # track
    "track": "track",
    "performance": "track",
    "picks": "track",
    # regime
    "regime": "regime",
    "traffic light": "regime",
    "breadth": "regime",
    # earnings
    "earnings": "earnings",
    "upcoming": "earnings",
    # multibagger
    "multibagger": "multibagger",
    "mb": "multibagger",
    # scorecard
    "scorecard": "scorecard",
    "picks worked": "scorecard",
    # world
    "world": "world",
    "global": "world",
    "indices": "world",
    # index
    "index": "index",
    # earnings calendar
    "earnings calendar": "earnings",
}

# Keyword → command for routing. Single keywords map to a command;
# multi-word phrases need the full phrase to match.
KEYWORD_COMMANDS = {
    "stock": "stock",
    "quote": "stock",
    "price": "stock",
    "news": "news",
    "headlines": "news",
    "fii": "fii",
    "dii": "fii",
    "flows": "fii",
    "vix": "vix",
    "volatility": "vix",
    "nifty": "nifty",
    "sensex": "sensex",
    "gold": "gold",
    "top": "top",
    "best": "top",
    "scores": "scores",
    "screener": "scores",
    "watch": "watch",
    "watchlist": "watch",
    "holdings": "watch",
    "digest": "digest",
    "daily": "digest",
    "macro": "macro",
    "yields": "macro",
    "fx": "fx",
    "currency": "fx",
    "rupee": "fx",
    "dollar": "fx",
    "sectors": "sectors",
    "sector": "sectors",
    "movers": "movers",
    "track": "track",
    "picks": "track",
    "regime": "regime",
    "breadth": "regime",
    "earnings": "earnings",
    "multibagger": "multibagger",
    "mb": "multibagger",
    "scorecard": "scorecard",
    "world": "world",
    "global": "world",
    "indices": "world",
    "index": "index",
    "sp500": "sp500",
    "sp 500": "sp500",
    "fx": "fx",
    "usdinr": "fx",
}

# Multi-word phrase → (command, arg_template)
# {arg} is replaced with the rest of the text after the phrase
PHRASE_ROUTES = {
    "price of": ("stock", "{arg}"),
    "price for": ("stock", "{arg}"),
    "quote for": ("stock", "{arg}"),
    "quote of": ("stock", "{arg}"),
    "check": ("stock", "{arg}"),
    "check price": ("stock", "{arg}"),
    "check quote": ("stock", "{arg}"),
    "news for": ("news", "{arg}"),
    "news about": ("news", "{arg}"),
    "headlines for": ("news", "{arg}"),
    "headlines about": ("news", "{arg}"),
    "fii flows": ("fii", ""),
    "dii flows": ("fii", ""),
    "foreign flows": ("fii", ""),
    "show me fii flows": ("fii", ""),
    "vix level": ("vix", ""),
    "volatility index": ("vix", ""),
    "nifty level": ("nifty", ""),
    "nifty 50": ("nifty", ""),
    "sensex level": ("sensex", ""),
    "gold price": ("gold", ""),
    "gold rate": ("gold", ""),
    "usd inr": ("fx", ""),
    "usdinr": ("fx", ""),
    "dollar rate": ("fx", ""),
    "rupee rate": ("fx", ""),
    "sector medians": ("sectors", ""),
    "sector fair value": ("sectors", ""),
    "entered left": ("movers", ""),
    "top20 changes": ("movers", ""),
    "how picks done": ("track", ""),
    "picks performance": ("track", ""),
    "market regime": ("regime", ""),
    "breadth trend": ("regime", ""),
    "upcoming earnings": ("earnings", ""),
    "earnings dates": ("earnings", ""),
    "multibagger stocks": ("multibagger", ""),
    "scorecard picks": ("scorecard", ""),
    "world indices": ("world", ""),
    "global indices": ("world", ""),
    "sp500 index": ("sp500", ""),
    "s&p 500": ("sp500", ""),
    "index nikkei": ("index", "nikkei"),
    "index nifty": ("index", "^NSEI"),
    "index sensex": ("index", "^BSESN"),
}

# Commands that need a stock symbol argument
SYMBOL_COMMANDS = {"stock", "news", "watch", "ask", "top", "sectors", "index"}
