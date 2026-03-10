"""hippomem CLI — entry point for hippomem serve."""


def main() -> None:
    import argparse
    import logging
    from logging.handlers import TimedRotatingFileHandler
    from pathlib import Path
    import uvicorn

    parser = argparse.ArgumentParser(prog="hippomem")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8719)
    serve.add_argument("--host", default="127.0.0.1")

    args = parser.parse_args()

    if args.command == "serve":
        # ── Logging ───────────────────────────────────────────────────────────
        log_dir = Path(".hippomem")
        log_dir.mkdir(exist_ok=True)

        root = logging.getLogger()
        root.setLevel(logging.INFO)

        # Terminal: warnings and errors only
        stream = logging.StreamHandler()
        stream.setLevel(logging.WARNING)
        stream.setFormatter(logging.Formatter("%(levelname)s  %(name)s  %(message)s"))
        root.addHandler(stream)

        # File: everything including INFO; rotate daily, keep 7 days
        file_handler = TimedRotatingFileHandler(
            filename=log_dir / "hippomem.log",
            when="D",
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(file_handler)

        # Silence uvicorn's own access log — request lines go to file via root
        logging.getLogger("uvicorn.access").propagate = False

        # ── Banner ────────────────────────────────────────────────────────────
        try:
            from importlib.metadata import version
            v = f"v{version('hippomem')}"
        except Exception:
            v = ""

        url = f"http://{args.host}:{args.port}"
        log_path = log_dir / "hippomem.log"
        _b, _d, _c, _r = "\033[1m", "\033[2m", "\033[36m", "\033[0m"

        def _link(href: str, label: str) -> str:
            return f"\033]8;;{href}\033\\{label}\033]8;;\033\\"

        print(f"\n  {_b}hippomem{_r}  {_d}{v}{_r}\n")
        print(f"  {_d}Your AI interactions deserve to be remembered — hippomem makes sure they are.{_r}")
        print(f"  {_d}Brain-inspired and built for the long term, it grows a rich memory corpus the more you use it.{_r}")
        print(f"  {_d}Connect any app or agent via API and let every interaction add to your growing wealth of context.{_r}")
        print()
        print(f"  Studio  →  {_c}{_link(url, url)}{_r}  {_d}Chat interface + visual memory explorer{_r}")
        print(f"  API     →  {_c}{_link(url, url)}{_r}  {_d}Connect your apps, agents, and integrations{_r}")
        print(f"  Logs    →  {_d}{log_path}{_r}")
        print()
        print(f"  {_d}Press Ctrl+C to stop{_r}\n")

        uvicorn.run(
            "hippomem.server.app:app",
            host=args.host,
            port=args.port,
            log_level="warning",
            access_log=False,
        )
    else:
        parser.print_help()
