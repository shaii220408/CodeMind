package sample.service;

public class NotificationService {
    private final KafkaProducer producer;
    public NotificationService(KafkaProducer producer) { this.producer = producer; }

    public void retryNotification(String message, int retries) {
        if (retries < 3) {
            producer.publish(message);
        }
    }
}
