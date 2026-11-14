"""Fictional vendors, buyer and item catalogue for the synthetic set.

GST rates are illustrative, not tax advice. Items that changed slab under GST 2.0 (22 Sep 2025)
use the change that was widely reported (e.g. air conditioners 28% -> 18%, hotel rooms up to
Rs 7,500 a night 12% -> 5%); everything else keeps one rate in both periods.
"""

from __future__ import annotations

from dataclasses import dataclass

from invoice_tool.gstin import checksum_char


def make_gstin(state: str, pan: str, entity: str = "1") -> str:
    first14 = f"{state}{pan}{entity}Z"
    return first14 + checksum_char(first14)


@dataclass(frozen=True)
class Item:
    description: str
    code: str | None  # HSN for goods, SAC for services
    rate_pre: float  # GST % before 22 Sep 2025
    rate_post: float  # GST % from 22 Sep 2025
    price_min: float
    price_max: float
    qty_max: int = 1


@dataclass(frozen=True)
class Party:
    key: str
    name: str
    state: str
    state_name: str
    pan: str
    address: str
    category: str = "Other"
    number_prefix: str = "INV-"
    items: tuple[Item, ...] = ()
    registered: bool = True  # unregistered small shops print no GSTIN and charge no GST

    @property
    def gstin(self) -> str | None:
        return make_gstin(self.state, self.pan) if self.registered else None


BUYER = Party(
    key="buyer",
    name="Demo Traders Pvt Ltd",
    state="27",
    state_name="Maharashtra",
    pan="AAJCD7315Q",
    address="Unit 4, Synthetic Business Park, Andheri East, Mumbai 400069",
)

VENDORS: dict[str, Party] = {
    v.key: v
    for v in [
        Party(
            key="stationery",
            name="Sahyadri Stationery Mart",
            state="27",
            state_name="Maharashtra",
            pan="AAKFS4821M",
            address="12 Ranade Road, Dadar West, Mumbai 400028",
            category="Office Supplies",
            number_prefix="SSM/{fy}/",
            items=(
                Item("A4 Copier Paper 75 GSM (500 sheets)", "4802", 18, 18, 260, 340, 20),
                Item("Ball Pen Blue (Box of 10)", "9608", 18, 18, 90, 140, 10),
                Item("Toner Cartridge 88A Compatible", "8443", 18, 18, 950, 1450, 4),
                Item("Box File Foolscap", "4820", 18, 18, 75, 120, 15),
                Item("Whiteboard Marker Set (4 colours)", "9608", 18, 18, 120, 180, 6),
            ),
        ),
        Party(
            key="cloud",
            name="Konkan Cloud Systems LLP",
            state="27",
            state_name="Maharashtra",
            pan="AAOFK2290R",
            address="401 Lake View Tower, Powai, Mumbai 400076",
            category="IT & Software",
            number_prefix="KCS-{year}-",
            items=(
                Item(
                    "Accounting Software Subscription (annual, 5 users)",
                    "998434",
                    18,
                    18,
                    18000,
                    26000,
                ),
                Item("Cloud Hosting - Standard Plan (monthly)", "998315", 18, 18, 4200, 6800),
                Item("Laptop 14in i5 16GB 512GB SSD", "8471", 18, 18, 52000, 61000, 2),
                Item("On-site IT Support (per visit)", "998713", 18, 18, 1500, 2500, 3),
            ),
        ),
        Party(
            key="cooling",
            name="Deccan Cooling Solutions Pvt Ltd",
            state="29",
            state_name="Karnataka",
            pan="AAGCD5517H",
            address="88 Industrial Suburb, Yeshwanthpur, Bengaluru 560022",
            category="Repairs & Maintenance",
            number_prefix="DCS/INV/{yymm}/",
            items=(
                Item("Split AC 1.5 Ton 3-Star Inverter", "8415", 28, 18, 31000, 38000, 2),
                Item("AC Annual Maintenance Contract (per unit)", "998719", 18, 18, 2200, 3200, 4),
                Item("Copper Pipe Installation Kit", "7411", 18, 18, 1800, 2600, 2),
            ),
        ),
        Party(
            key="bistro",
            name="Marine Drive Bistro",
            state="27",
            state_name="Maharashtra",
            pan="AAQFM6403C",
            address="Shop 3, Sea Face Lane, Churchgate, Mumbai 400020",
            category="Meals & Entertainment",
            number_prefix="B-",
            items=(
                Item("Paneer Tikka", None, 5, 5, 320, 380, 2),
                Item("Veg Biryani", None, 5, 5, 290, 340, 3),
                Item("Masala Dosa", None, 5, 5, 160, 210, 3),
                Item("Fresh Lime Soda", None, 5, 5, 110, 140, 4),
                Item("Filter Coffee", None, 5, 5, 70, 95, 4),
            ),
        ),
        Party(
            key="hotel",
            name="Hotel Western Ghats Residency",
            state="27",
            state_name="Maharashtra",
            pan="AAEFH9032K",
            address="Old Highway, Lonavala, Pune District 410401",
            category="Travel",
            number_prefix="HWG-{yy}-",
            items=(
                Item(
                    "Deluxe Room (per night, tariff up to Rs 7,500)", "996311", 12, 5, 4200, 6500, 3
                ),
                Item("Conference Hall Rental (half day)", "997212", 18, 18, 9000, 14000),
            ),
        ),
        Party(
            key="legal",
            name="Indus Legal & Tax Advisors",
            state="07",
            state_name="Delhi",
            pan="AACFI3378N",
            address="B-14 Connaught Place, New Delhi 110001",
            category="Professional Services",
            number_prefix="ILTA/{year}/",
            items=(
                Item("GST Return Filing - Quarterly Retainer", "998231", 18, 18, 15000, 22000),
                Item("Contract Review (per hour)", "998212", 18, 18, 3500, 4500, 8),
                Item("Company Secretarial Compliance - Annual", "998222", 18, 18, 30000, 42000),
            ),
        ),
        Party(
            key="cabs",
            name="Aarey Fleet Cabs",
            state="27",
            state_name="Maharashtra",
            pan="AAIFA1146D",
            address="Aarey Road, Goregaon East, Mumbai 400065",
            category="Travel",
            number_prefix="AFC",
            items=(
                Item("Airport Transfer - Sedan", "996412", 5, 5, 850, 1350),
                Item("Local Hire 8 hrs / 80 km - Sedan", "996412", 5, 5, 2200, 2900),
            ),
        ),
        Party(
            key="furniture",
            name="Gujarat Office Furniture Works",
            state="24",
            state_name="Gujarat",
            pan="AAHFG8124P",
            address="Plot 21, GIDC Estate, Vatva, Ahmedabad 382445",
            category="Office Supplies",
            number_prefix="GOFW/{fy}/",
            items=(
                Item("Ergonomic Office Chair - Mesh Back", "9401", 18, 18, 6200, 8900, 6),
                Item("Workstation Desk 1200x600", "9403", 18, 18, 9800, 13500, 4),
                Item("Steel Storage Cabinet 4-Door", "9403", 18, 18, 11500, 15500, 2),
            ),
        ),
        Party(
            key="courier",
            name="Powai Print & Courier Hub",
            state="27",
            state_name="Maharashtra",
            pan="AAPFP4470E",
            address="Hiranandani Gardens, Powai, Mumbai 400076",
            category="Other",
            number_prefix="PPC/{year}/",
            items=(
                Item("Courier - Domestic Express (per kg)", "996812", 18, 18, 180, 260, 12),
                Item("Colour Printing A3 (per sheet)", "998912", 18, 18, 35, 60, 80),
                Item("Spiral Binding", "998912", 18, 18, 60, 90, 10),
            ),
        ),
        Party(
            key="bakery",
            name="Bandra Bakehouse & Cafe",
            state="27",
            state_name="Maharashtra",
            pan="AACFB7712G",
            address="21 Hill Road, Bandra West, Mumbai 400050",
            category="Meals & Entertainment",
            number_prefix="BBC/",
            items=(
                Item("Cappuccino", None, 5, 5, 160, 210, 4),
                Item("Croissant", None, 5, 5, 120, 160, 4),
                Item("Chocolate Brownie", None, 5, 5, 140, 180, 3),
                Item("Club Sandwich", None, 5, 5, 260, 320, 2),
            ),
        ),
        Party(
            key="kiosk",
            name="Juhu Chai & Snacks Corner",
            state="27",
            state_name="Maharashtra",
            pan="",
            address="Stall 7, Juhu Tara Road, Mumbai 400049",
            category="Meals & Entertainment",
            registered=False,
            items=(
                Item("Cutting Chai", None, 0, 0, 15, 25, 6),
                Item("Vada Pav", None, 0, 0, 20, 30, 4),
                Item("Bun Maska", None, 0, 0, 30, 45, 3),
            ),
        ),
    ]
}
