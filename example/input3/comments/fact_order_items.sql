COMMENT ON TABLE fact_order_items IS '订单明细事实表，记录每个订单下的商品行项目';
COMMENT ON COLUMN fact_order_items.order_id IS '订单ID';
COMMENT ON COLUMN fact_order_items.product_id IS '商品ID';
COMMENT ON COLUMN fact_order_items.quantity IS '购买件数';
COMMENT ON COLUMN fact_order_items.unit_price IS '下单时商品单价';
