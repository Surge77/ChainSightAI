"""All 53 columns of `DataCoSupplyChainDataset.csv`, and the decision made about each.

This is the executable twin of `docs/data_audit.md`. The document carries the argument;
this file carries the decision, and a test asserts the two agree. Neither can drift
without the other failing.

Every equality claimed in a `why` was measured on the full 180,519 rows, not assumed from
a column name.

The file is one row per column, and is exempt from both the line-length rule and the
formatter (see `pyproject.toml`). Wrapping each row across six lines would triple its
length, push it past the 300-line ceiling, and turn a table you can read down into
something you have to scroll through.
"""

from __future__ import annotations

from chainsight.contract import Availability, Column, Disposition

AT_ORDER = Availability.AT_ORDER
POST = Availability.POST_DISPATCH
NEVER = Availability.NEVER

USE = Disposition.USE
TARGET = Disposition.TARGET
LEAK = Disposition.DROP_LEAK
PII = Disposition.DROP_PII
IDENT = Disposition.DROP_ID
DUPE = Disposition.DROP_DUPLICATE
CONST = Disposition.DROP_CONSTANT


COLUMNS: tuple[Column, ...] = (
    Column("Type", AT_ORDER, USE, "Payment method, chosen at checkout. TRANSFER runs 8-12pp less late than the other three inside every shipping mode."),
    Column("Days for shipping (real)", POST, LEAK, "Actual transit time. With the scheduled days it reconstructs the classification target exactly."),
    Column("Days for shipment (scheduled)", AT_ORDER, DUPE, "A perfect 1:1 bijection with Shipping Mode: 0=Same Day, 1=First Class, 2=Second Class, 4=Standard Class. The same variable twice."),
    Column("Benefit per order", POST, LEAK, "Byte-identical to Order Profit Per Order on all 180,519 rows, which is the regression target multiplied by the order total."),
    Column("Sales per customer", AT_ORDER, DUPE, "Byte-identical to Order Item Total on all 180,519 rows."),
    Column("Delivery Status", POST, LEAK, "Separates the target perfectly: 'Late delivery' is exactly the 98,977 positive rows and nothing else appears there."),
    Column("Late_delivery_risk", POST, TARGET, "The classification target. Equals (real > scheduled) on 176,096 rows; all 4,423 exceptions are 'Shipping canceled'."),
    Column("Category Id", AT_ORDER, DUPE, "Identical to Product Category Id, and Category Name is the readable form of the same 50 levels."),
    Column("Category Name", AT_ORDER, USE, "50 product categories. The readable key kept in place of two integer twins."),
    Column("Customer City", AT_ORDER, IDENT, "563 levels naming where one customer lives. Near-identifying, and geography carries almost no signal here."),
    Column("Customer Country", AT_ORDER, USE, "Two levels, EE. UU. and Puerto Rico. Cheap, and pairs with Order Country to say whether a shipment crosses a border."),
    Column("Customer Email", NEVER, PII, "Personal data. Masked to a single constant in this release, which does not make it a column to read."),
    Column("Customer Fname", NEVER, PII, "Personal data."),
    Column("Customer Id", AT_ORDER, IDENT, "20,652 levels. A model that learns a customer id has memorised the table, not the problem."),
    Column("Customer Lname", NEVER, PII, "Personal data."),
    Column("Customer Password", NEVER, PII, "A password column in a public teaching dataset. Never read, never stored, never logged."),
    Column("Customer Segment", AT_ORDER, USE, "Consumer, Corporate or Home Office. Three levels, known at checkout."),
    Column("Customer State", AT_ORDER, USE, "46 levels. Coarse enough not to locate a household, fine enough to carry regional effects if any exist."),
    Column("Customer Street", NEVER, PII, "Personal data. Locates a household."),
    Column("Customer Zipcode", NEVER, PII, "Personal data. Locates a household to a few streets."),
    Column("Department Id", AT_ORDER, DUPE, "Department Name is the readable form of the same 11 levels."),
    Column("Department Name", AT_ORDER, USE, "11 departments, from Fan Shop at 66,861 rows to Health and Beauty at 362."),
    Column("Latitude", NEVER, PII, "11,250 distinct customer coordinates. A street address in another notation."),
    Column("Longitude", NEVER, PII, "As Latitude."),
    Column("Market", AT_ORDER, USE, "Five levels. Kept for reporting rather than for signal: late rate ranges 0.5436 to 0.5521 across all five, which is noise."),
    Column("Order City", AT_ORDER, IDENT, "3,597 levels. Order Region and Order Country say the same thing without one level per town."),
    Column("Order Country", AT_ORDER, USE, "164 destinations. High cardinality under LabelEncoder, so it helps trees and misleads the linear models; the model card says so."),
    Column("Order Customer Id", AT_ORDER, DUPE, "Identical to Customer Id on all 180,519 rows."),
    Column("order date (DateOrders)", AT_ORDER, USE, "The moment the order is placed. Used for the time-aware split and for derived calendar features, never as a raw number."),
    Column("Order Id", AT_ORDER, IDENT, "65,752 orders. An identifier."),
    Column("Order Item Cardprod Id", AT_ORDER, DUPE, "Identical to Product Card Id on all 180,519 rows."),
    Column("Order Item Discount", AT_ORDER, DUPE, "Sales minus Order Item Total to within a hundredth of a currency unit. The rate carries the same information scale-free."),
    Column("Order Item Discount Rate", AT_ORDER, USE, "18 discrete rates from 0.00 to 0.25."),
    Column("Order Item Id", AT_ORDER, IDENT, "One value per row. A row number wearing a business name."),
    Column("Order Item Product Price", AT_ORDER, DUPE, "Identical to Product Price on all 180,519 rows."),
    Column("Order Item Profit Ratio", POST, TARGET, "The regression target: margin as a fraction of the order total. Ranges -2.75 to 0.50; 18.7% of rows are loss-making."),
    Column("Order Item Quantity", AT_ORDER, USE, "1 to 5 units. Just over half of all rows are single-unit."),
    Column("Sales", AT_ORDER, DUPE, "Exactly Product Price times Order Item Quantity, both of which are kept."),
    Column("Order Item Total", AT_ORDER, USE, "The line value after discount. Kept because the decision engine multiplies it by the predicted margin; the feature builder may still drop it as collinear."),
    Column("Order Profit Per Order", POST, LEAK, "The regression target multiplied by the order total. Keeping it hands the model the answer."),
    Column("Order Region", AT_ORDER, USE, "23 regions. Real but small: 0.488 to 0.580 late, and the extremes sit on the smallest groups."),
    Column("Order State", AT_ORDER, IDENT, "1,089 levels. Order Region covers the same geography at a usable cardinality."),
    Column("Order Status", POST, LEAK, "Assigned after the fact. SUSPECTED_FRAUD and CANCELED cannot be known when the order is placed."),
    Column("Order Zipcode", NEVER, PII, "Personal data, and 86% null besides."),
    Column("Product Card Id", AT_ORDER, DUPE, "118 levels; Product Name is the readable form of the same catalogue."),
    Column("Product Category Id", AT_ORDER, DUPE, "Identical to Category Id on all 180,519 rows."),
    Column("Product Description", AT_ORDER, CONST, "Null on all 180,519 rows."),
    Column("Product Image", AT_ORDER, IDENT, "A URL per product. Product Name is the same key, readable."),
    Column("Product Name", AT_ORDER, USE, "118 products. The readable catalogue key."),
    Column("Product Price", AT_ORDER, USE, "75 distinct list prices."),
    Column("Product Status", AT_ORDER, CONST, "Zero on all 180,519 rows."),
    Column("shipping date (DateOrders)", POST, LEAK, "Subtracting the order date reconstructs the real transit time, and with it the target."),
    Column("Shipping Mode", AT_ORDER, USE, "The dominant signal by a wide margin: 38.1% late on Standard Class against 95.3% on First Class."),
)
