"""
PolyBob TUI - Terminal User Interface

A real-time terminal dashboard for monitoring Polymarket markets.
"""
import asyncio
import httpx
from datetime import datetime
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich import box

API_BASE = "http://localhost:8000"


class PolyBobTUI:
    """Terminal UI for PolyBob"""

    def __init__(self):
        self.console = Console()
        self.watchlist = []
        self.features = {}
        self.selected_index = 0
        self.is_connected = False
        self.last_update = None

    async def fetch_data(self):
        """Fetch data from API"""
        async with httpx.AsyncClient() as client:
            try:
                # Fetch watchlist
                response = await client.get(f"{API_BASE}/markets/watchlist", timeout=5.0)
                data = response.json()
                self.watchlist = data.get("watchlist", [])
                self.is_connected = True

                # Fetch features for all markets
                for market_id in self.watchlist:
                    try:
                        response = await client.get(
                            f"{API_BASE}/markets/{market_id}/features",
                            timeout=5.0,
                        )
                        self.features[market_id] = response.json()
                    except Exception:
                        pass

                self.last_update = datetime.now()

            except Exception as e:
                self.is_connected = False
                self.console.print(f"[red]Error fetching data: {e}[/red]")

    def create_header(self) -> Panel:
        """Create header panel"""
        status = "[green]●[/green] CONNECTED" if self.is_connected else "[red]●[/red] DISCONNECTED"
        update_time = self.last_update.strftime("%H:%M:%S") if self.last_update else "N/A"

        header_text = Text()
        header_text.append("▓ POLYBOB TERMINAL ▓", style="bold green")
        header_text.append(f"  |  {status}  |  ", style="dim")
        header_text.append(f"Markets: {len(self.watchlist)}", style="cyan")
        header_text.append(f"  |  Last Update: {update_time}", style="dim")

        return Panel(
            header_text,
            box=box.DOUBLE,
            style="green",
        )

    def create_market_list(self) -> Table:
        """Create market list table"""
        table = Table(
            title="[bold green]═══ WATCHLIST ═══[/bold green]",
            box=box.HEAVY,
            show_header=True,
            header_style="bold cyan",
            border_style="green",
        )

        table.add_column("ID", style="dim", width=20)
        table.add_column("MID", justify="right", style="cyan")
        table.add_column("SPREAD", justify="right")
        table.add_column("VOL", justify="right", style="yellow")
        table.add_column("STATUS", justify="center")

        for i, market_id in enumerate(self.watchlist):
            feature = self.features.get(market_id)

            if feature:
                mid_price = f"{feature['mid_price']:.4f}"
                spread = feature['spread_bps']
                spread_str = f"{spread:.1f}bp"
                spread_style = "red" if spread > 100 else "green"
                volume = f"{feature['volume_1m']:.0f}"

                # Status indicator
                if spread > 200 or feature['price_jump_score'] > 3:
                    status = "[red blink]⚠ ALERT[/red blink]"
                elif spread > 100 or feature['price_jump_score'] > 2:
                    status = "[yellow]⚠ WARN[/yellow]"
                else:
                    status = "[green]✓ OK[/green]"

                # Highlight selected row
                style = "bold" if i == self.selected_index else None

                table.add_row(
                    market_id[:18] + "...",
                    mid_price,
                    Text(spread_str, style=spread_style),
                    volume,
                    status,
                    style=style,
                )
            else:
                table.add_row(
                    market_id[:18] + "...",
                    "---",
                    "---",
                    "---",
                    "[dim]LOADING[/dim]",
                )

        return table

    def create_market_detail(self) -> Panel:
        """Create market detail panel"""
        if not self.watchlist or self.selected_index >= len(self.watchlist):
            return Panel(
                "[dim]No market selected[/dim]",
                title="[bold green]═══ MARKET DETAIL ═══[/bold green]",
                box=box.HEAVY,
                border_style="green",
            )

        market_id = self.watchlist[self.selected_index]
        feature = self.features.get(market_id)

        if not feature:
            return Panel(
                "[dim]Loading market data...[/dim]",
                title=f"[bold green]═══ {market_id[:16]}... ═══[/bold green]",
                box=box.HEAVY,
                border_style="green",
            )

        # Create detail table
        detail = Table(show_header=False, box=None, padding=(0, 2))
        detail.add_column("Label", style="dim")
        detail.add_column("Value", style="bold")

        detail.add_row("Market ID", market_id)
        detail.add_row("Mid Price", f"[cyan]{feature['mid_price']:.4f}[/cyan]")
        detail.add_row("Bid Price", f"[green]{feature['bid_price']:.4f}[/green]")
        detail.add_row("Ask Price", f"[red]{feature['ask_price']:.4f}[/red]")
        detail.add_row("Spread (bps)", f"{feature['spread_bps']:.2f}")
        detail.add_row("Bid Size", f"{feature['bid_size']:.2f}")
        detail.add_row("Ask Size", f"{feature['ask_size']:.2f}")
        detail.add_row("Depth Imbalance", f"{feature['depth_imbalance']:.3f}")
        detail.add_row("Trade Intensity", f"{feature['trade_intensity_1m']}")
        detail.add_row("Volume (1m)", f"{feature['volume_1m']:.2f}")
        detail.add_row("Price Jump Score", f"{feature['price_jump_score']:.2f}")

        return Panel(
            detail,
            title=f"[bold green]═══ {market_id[:16]}... ═══[/bold green]",
            box=box.HEAVY,
            border_style="green",
        )

    def create_layout(self) -> Layout:
        """Create main layout"""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )

        layout["body"].split_row(
            Layout(name="markets", ratio=2),
            Layout(name="detail", ratio=3),
        )

        # Populate layout
        layout["header"].update(self.create_header())
        layout["markets"].update(self.create_market_list())
        layout["detail"].update(self.create_market_detail())

        # Footer
        footer_text = Text()
        footer_text.append("Controls: ", style="dim")
        footer_text.append("↑/↓", style="bold cyan")
        footer_text.append(" Navigate  ", style="dim")
        footer_text.append("Q", style="bold cyan")
        footer_text.append(" Quit  ", style="dim")
        footer_text.append("R", style="bold cyan")
        footer_text.append(" Refresh", style="dim")

        layout["footer"].update(
            Panel(footer_text, box=box.DOUBLE, style="green")
        )

        return layout

    async def run(self):
        """Run the TUI"""
        self.console.clear()
        self.console.print("[bold green]Starting PolyBob TUI...[/bold green]")

        # Initial data fetch
        await self.fetch_data()

        with Live(
            self.create_layout(),
            console=self.console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            while True:
                try:
                    # Update display
                    live.update(self.create_layout())

                    # Fetch new data every 5 seconds
                    await asyncio.sleep(5)
                    await self.fetch_data()

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    self.console.print(f"[red]Error: {e}[/red]")
                    await asyncio.sleep(1)


async def main():
    """Main entry point"""
    tui = PolyBobTUI()
    try:
        await tui.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[bold green]PolyBob TUI stopped.[/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
