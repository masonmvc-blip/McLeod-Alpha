from types import SimpleNamespace

from execution.emergency_exit import flatten_all_spy_options


class Response:
    def __init__(self, payload=None, location=None):
        self.payload = payload or {}
        self.headers = {"Location": location} if location else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Client:
    Account = SimpleNamespace(
        Fields=SimpleNamespace(POSITIONS="POSITIONS"),
    )

    def __init__(self):
        self.snapshots = [
            ([{"instrument": {"assetType": "OPTION", "symbol": "SPY TEST"},
               "longQuantity": 7}], [{"orderId": "stop-1", "status": "WORKING",
                                      "orderLegCollection": [{"instruction": "SELL_TO_CLOSE",
                                      "instrument": {"assetType": "OPTION", "symbol": "SPY TEST"}}]}]),
            ([{"instrument": {"assetType": "OPTION", "symbol": "SPY TEST"},
               "longQuantity": 7}], []),
            ([], []),
        ]
        self.snapshot_index = 0
        self.canceled = []
        self.placed = []

    def get_account(self, account_hash, fields):
        positions, _ = self.snapshots[min(self.snapshot_index, len(self.snapshots) - 1)]
        return Response({"securitiesAccount": {"positions": positions}})

    def get_orders_for_account(self, account_hash):
        _, orders = self.snapshots[min(self.snapshot_index, len(self.snapshots) - 1)]
        self.snapshot_index += 1
        return Response(orders)

    def cancel_order(self, order_id, account_hash):
        self.canceled.append(order_id)
        return Response()

    def place_order(self, account_hash, order):
        self.placed.append(order)
        return Response(location="/accounts/hash/orders/exit-1")


def test_kill_switch_cancels_reservations_closes_full_broker_quantity_and_verifies_flat():
    client = Client()

    result = flatten_all_spy_options(client, "hash", poll_seconds=0)

    assert result["status"] == "flat"
    assert result["initial_positions"] == {"SPY TEST": 7}
    assert result["canceled_order_ids"] == ["stop-1"]
    assert result["submitted_orders"][0]["quantity"] == 7
    assert result["submitted_orders"][0]["order_id"] == "exit-1"
    assert len(client.placed) == 1
