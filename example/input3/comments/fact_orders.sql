COMMENT ON TABLE fact_orders IS '订单事实表，记录订单主信息与支付状态';
COMMENT ON COLUMN fact_orders.order_id IS '订单ID';
COMMENT ON COLUMN fact_orders.user_id IS '下单用户ID';
COMMENT ON COLUMN fact_orders.region IS '用户下单地区';
COMMENT ON COLUMN fact_orders.order_date IS '订单创建日期';
COMMENT ON COLUMN fact_orders.paid_at IS '订单支付完成时间';
COMMENT ON COLUMN fact_orders.order_status IS '订单状态，例如 PAID 或 CANCELED';
