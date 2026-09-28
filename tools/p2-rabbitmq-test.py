"""
P2 / mall-portal 的 RabbitMQ 端到端验证。

验证的不是「端口起来了」，而是**订单超时取消那条链路真的能跑**：

    mall.order.direct.ttl (direct exchange)
        |
        |  routing key: mall.order.cancel.ttl
        v
    mall.order.cancel.ttl   (队列, 带 TTL + 死信参数)
        |
        |  TTL 到期 -> 死信转发
        |  x-dead-letter-exchange     = mall.order.direct
        |  x-dead-letter-routing-key  = mall.order.cancel
        v
    mall.order.direct (direct exchange)
        |
        |  routing key: mall.order.cancel
        v
    mall.order.cancel       (队列, 由 CancelOrderReceiver 消费 -> 取消订单)

拓扑来自（不是猜的）：
  mall-portal/src/main/java/com/macro/mall/portal/domain/QueueEnum.java
  mall-portal/src/main/java/com/macro/mall/portal/config/RabbitMqConfig.java

连接信息来自：
  mall-portal/src/main/resources/application.yml
      spring.rabbitmq: host localhost, port 5672,
                       virtual-host /mall, username mall, password mall
"""

import sys
import time
import json

import pika

HOST = "127.0.0.1"
PORT = 5672
VHOST = "/mall"
USER = "mall"
PASS = "mall"

EX_CANCEL = "mall.order.direct"
Q_CANCEL = "mall.order.cancel"
RK_CANCEL = "mall.order.cancel"

EX_TTL = "mall.order.direct.ttl"
Q_TTL = "mall.order.cancel.ttl"
RK_TTL = "mall.order.cancel.ttl"

TTL_MS = 3000

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail else ""))


def main():
    print("=" * 74)
    print("P2 / mall-portal RabbitMQ 端到端验证")
    print(f"  {USER}@{HOST}:{PORT}  vhost={VHOST}")
    print("=" * 74)

    # ---- 1) 连接 ----------------------------------------------------------
    print("\n[1] 连接与鉴权")
    try:
        creds = pika.PlainCredentials(USER, PASS)
        params = pika.ConnectionParameters(
            host=HOST, port=PORT, virtual_host=VHOST,
            credentials=creds, heartbeat=30,
            connection_attempts=3, retry_delay=1,
        )
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        # pika 的 BlockingConnection 不直接暴露 server_properties，
        # 它在底层 adapter 上。取不到也不影响结论，所以容错处理。
        ver = "?"
        try:
            ver = conn._impl.server_properties.get("version", "?")
        except Exception:
            pass
        check("TCP + AMQP 握手 + 账号/vhost 鉴权", True, f"broker version={ver}")
    except Exception as e:
        check("连接", False, f"{type(e).__name__}: {e}")
        return report()

    # ---- 2) 声明拓扑 ------------------------------------------------------
    print("\n[2] 声明交换机 / 队列 / 绑定（与 RabbitMqConfig.java 一致）")
    try:
        ch.exchange_declare(EX_CANCEL, exchange_type="direct", durable=True)
        ch.exchange_declare(EX_TTL, exchange_type="direct", durable=True)

        ch.queue_declare(Q_CANCEL, durable=True)
        ch.queue_bind(Q_CANCEL, EX_CANCEL, RK_CANCEL)

        # 关键：TTL 队列必须带死信参数，否则消息过期后直接丢弃
        ch.queue_declare(Q_TTL, durable=True, arguments={
            "x-dead-letter-exchange": EX_CANCEL,
            "x-dead-letter-routing-key": RK_CANCEL,
        })
        ch.queue_bind(Q_TTL, EX_TTL, RK_TTL)
        check("两个 direct 交换机 + 两个队列 + 两条绑定", True)
    except Exception as e:
        check("声明拓扑", False, f"{type(e).__name__}: {e}")
        conn.close()
        return report()

    # ---- 3) 清空可能的历史消息 -------------------------------------------
    # 上一次测试留下的消息会让「收到的第一条」不是本次发的，导致误判。
    # pika 的 basic_get 返回三元组 (method, properties, body)；
    # 队列为空时返回 (None, None, None)。
    drained = 0
    while True:
        method, _, body = ch.basic_get(Q_CANCEL, auto_ack=True)
        if method is None:
            break
        drained += 1
    check("清空取消队列的历史消息", True, f"清掉 {drained} 条")

    # ---- 4) 发一条带 TTL 的消息 ------------------------------------------
    print(f"\n[3] 投递订单超时消息（TTL={TTL_MS}ms）")
    order_id = 20260928
    payload = {"orderId": order_id, "note": "中文测试-订单超时取消"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    ch.basic_publish(
        exchange=EX_TTL,
        routing_key=RK_TTL,
        body=body,
        properties=pika.BasicProperties(
            delivery_mode=2,                 # 持久化
            expiration=str(TTL_MS),          # 毫秒
            content_type="application/json",
        ),
    )
    check("publish -> mall.order.direct.ttl", True, f"orderId={order_id}")

    # 投递后消息应该还在 TTL 队列里，没到取消队列
    time.sleep(0.5)
    method, _, body = ch.basic_get(Q_CANCEL, auto_ack=True)
    check("TTL 未到期时取消队列为空（延迟确实生效）", method is None,
          "符合预期" if method is None else "！消息提前到了，死信参数可能没生效")

    # ---- 5) 等待 TTL 到期 + 死信转发 -------------------------------------
    print(f"\n[4] 等待 {TTL_MS}ms TTL 到期，观察死信转发")
    got = None
    t0 = time.time()
    deadline = t0 + (TTL_MS / 1000.0) + 8
    while time.time() < deadline:
        method, props, body = ch.basic_get(Q_CANCEL, auto_ack=True)
        if method is not None:
            got = (method, props, body)
            break
        time.sleep(0.25)

    if got is None:
        check("死信转发到 mall.order.cancel", False, "超时未收到消息")
    else:
        method, props, body = got
        elapsed = time.time() - t0
        check("死信转发到 mall.order.cancel", True,
              f"收到 {len(body)} 字节，耗时 {elapsed:.1f}s（TTL 设定 {TTL_MS/1000:.1f}s）")

        # 内容与编码
        decoded = None
        try:
            decoded = json.loads(body.decode("utf-8"))
            check("消息体是合法 UTF-8 JSON", True, str(decoded))
        except Exception as e:
            check("消息体是合法 UTF-8 JSON", False, f"{type(e).__name__}: {e}")

        if decoded is not None:
            check("orderId 正确", decoded.get("orderId") == order_id,
                  str(decoded.get("orderId")))
            check("中文完整（无乱码）",
                  decoded.get("note") == "中文测试-订单超时取消",
                  repr(decoded.get("note")))
        check("消息为持久化投递", bool(props.delivery_mode) if props else False,
              f"delivery_mode={props.delivery_mode if props else '?'}")

    # ---- 6) 队列状态复核 --------------------------------------------------
    print("\n[5] 队列状态复核")
    try:
        ok = ch.queue_declare(Q_TTL, durable=True, passive=True)
        check("TTL 队列已排空（消息已转发走）", ok.method.message_count == 0,
              f"message_count={ok.method.message_count}")
    except Exception as e:
        check("TTL 队列状态", False, str(e))

    conn.close()
    return report()


def report():
    print("\n" + "=" * 74)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    if passed == total:
        print(f"结果：全部通过（{passed}/{total}）—— RabbitMQ 端到端可用")
        print("      mall-portal 的订单超时取消链路（含 TTL + 死信）验证完毕")
        code = 0
    else:
        print(f"结果：{passed}/{total} 通过，存在失败项")
        for name, ok, detail in results:
            if not ok:
                print(f"   FAIL: {name}  {detail}")
        code = 1
    print("=" * 74)
    return code


if __name__ == "__main__":
    sys.exit(main())
