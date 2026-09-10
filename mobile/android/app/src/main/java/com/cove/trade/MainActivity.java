package com.cove.trade;

import android.os.Bundle;
import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.PendingPurchasesParams;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private BillingClient billingClient;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        billingClient =
            BillingClient.newBuilder(this)
                .setListener((billingResult, purchases) -> {})
                .enablePendingPurchases(
                    PendingPurchasesParams.newBuilder().enableOneTimeProducts().build()
                )
                .enableAutoServiceReconnection()
                .build();
        billingClient.startConnection(
            new BillingClientStateListener() {
                @Override
                public void onBillingSetupFinished(BillingResult billingResult) {}

                @Override
                public void onBillingServiceDisconnected() {}
            }
        );
    }
}
