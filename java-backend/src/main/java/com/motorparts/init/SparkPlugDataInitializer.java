package com.motorparts.init;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * 火花塞产品数据初始化器（独立运行版本）
 *
 * 使用方法：
 * 1. 先确保Spring Boot项目运行在配置的端口上
 * 2. 直接在IDE中运行 main 方法
 *
 * 功能：
 * 1. 创建/更新3个火花塞供应商（DENSO、BOSCH、NGK）
 * 2. 创建/更新3个火花塞零部件
 * 3. 创建入库记录
 * 4. 创建2024-2025年历史订单
 *
 * 特点：支持重复运行，已存在的数据会更新，不存在的数据会创建
 */
public class SparkPlugDataInitializer {

    private static final String BASE_URL = buildBaseUrl();
    private static final HttpClient httpClient = HttpClient.newHttpClient();
    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd");
    // 后端 CustomLocalDateTimeDeserializer 期望格式: yyyy-MM-dd'T'HH:mm:ss.SSS
    private static final DateTimeFormatter DATETIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS");
    private static final Random random = new Random();
    private static final boolean DEBUG = false;

    private static String buildBaseUrl() {
        String port = System.getProperty("server.port");
        if (port == null || port.isBlank()) {
            port = System.getenv().getOrDefault("SERVER_PORT", "8080");
        }
        return "http://localhost:" + port + "/api";
    }

    public static void main(String[] args) {
        System.out.println("==============================================");
        System.out.println("      火花塞产品数据初始化程序");
        System.out.println("==============================================");
        System.out.println();

        try {
            // 1. 创建/更新供应商
            System.out.println("\n>>> 第1步：创建/更新供应商...");
            Map<String, Long> supplierIds = createOrUpdateSuppliers();

            // 2. 创建/更新零部件
            System.out.println("\n>>> 第2步：创建/更新零部件...");
            Map<String, Long> partIds = createOrUpdateParts(supplierIds);

            // 3. 创建入库记录
            System.out.println("\n>>> 第3步：创建入库记录...");
            createInboundRecords(partIds);

            // 4. 创建历史订单
            System.out.println("\n>>> 第4步：创建历史订单...");
            createHistoricalOrders(partIds, supplierIds);

            System.out.println("\n==============================================");
            System.out.println("      数据初始化完成！");
            System.out.println("==============================================");

            // 打印摘要
            printSummary(partIds, supplierIds);

        } catch (Exception e) {
            System.err.println("\n!!! 数据初始化失败: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private static String sendPostRequestRaw(String url, String jsonBody) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        return response.body();
    }

    private static String sendGetRequestRaw(String url) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Content-Type", "application/json")
                .GET()
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        return response.body();
    }

    private static String sendPutRequestRaw(String url, String jsonBody) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Content-Type", "application/json")
                .PUT(HttpRequest.BodyPublishers.ofString(jsonBody))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        return response.body();
    }

    private static String toJson(Map<String, Object> map) {
        StringBuilder sb = new StringBuilder();
        sb.append("{");
        boolean first = true;
        for (Map.Entry<String, Object> entry : map.entrySet()) {
            if (!first) sb.append(",");
            first = false;
            sb.append("\"").append(entry.getKey()).append("\":");
            Object value = entry.getValue();
            if (value == null) {
                sb.append("null");
            } else if (value instanceof String) {
                sb.append("\"").append(escapeJson((String) value)).append("\"");
            } else if (value instanceof Number) {
                sb.append(value);
            } else if (value instanceof List) {
                sb.append(toJsonArray((List) value));
            } else if (value instanceof Map) {
                sb.append(toJson((Map) value));
            } else {
                sb.append("\"").append(escapeJson(value.toString())).append("\"");
            }
        }
        sb.append("}");
        return sb.toString();
    }

    private static String toJsonArray(List list) {
        StringBuilder sb = new StringBuilder();
        sb.append("[");
        boolean first = true;
        for (Object item : list) {
            if (!first) sb.append(",");
            first = false;
            if (item instanceof Map) {
                sb.append(toJson((Map) item));
            } else if (item instanceof String) {
                sb.append("\"").append(escapeJson((String) item)).append("\"");
            } else if (item instanceof Number) {
                sb.append(item);
            } else {
                sb.append("\"").append(escapeJson(item.toString())).append("\"");
            }
        }
        sb.append("]");
        return sb.toString();
    }

    private static String escapeJson(String str) {
        return str.replace("\\", "\\\\")
                  .replace("\"", "\\\"")
                  .replace("\n", "\\n")
                  .replace("\r", "\\r")
                  .replace("\t", "\\t");
    }

    private static Long extractIdFromResponse(String jsonResponse) {
        if (jsonResponse == null || jsonResponse.isEmpty()) {
            return null;
        }
        int idIndex = jsonResponse.indexOf("\"id\":");
        if (idIndex == -1) {
            idIndex = jsonResponse.indexOf("id\":");
        }
        if (idIndex != -1) {
            int start = idIndex + 5;
            while (start < jsonResponse.length() && (jsonResponse.charAt(start) == ' ' || jsonResponse.charAt(start) == '"')) {
                start++;
            }
            StringBuilder numStr = new StringBuilder();
            while (start < jsonResponse.length()) {
                char c = jsonResponse.charAt(start);
                if (Character.isDigit(c)) {
                    numStr.append(c);
                    start++;
                } else {
                    break;
                }
            }
            if (numStr.length() > 0) {
                try {
                    return Long.parseLong(numStr.toString());
                } catch (NumberFormatException e) {
                    // 忽略
                }
            }
        }
        return null;
    }

    private static Integer extractCodeFromResponse(String jsonResponse) {
        if (jsonResponse == null || jsonResponse.isEmpty()) {
            return null;
        }
        int codeIndex = jsonResponse.indexOf("\"code\":");
        if (codeIndex != -1) {
            int start = codeIndex + 7;
            while (start < jsonResponse.length() && jsonResponse.charAt(start) == ' ') {
                start++;
            }
            StringBuilder numStr = new StringBuilder();
            while (start < jsonResponse.length()) {
                char c = jsonResponse.charAt(start);
                if (Character.isDigit(c)) {
                    numStr.append(c);
                    start++;
                } else {
                    break;
                }
            }
            if (numStr.length() > 0) {
                try {
                    return Integer.parseInt(numStr.toString());
                } catch (NumberFormatException e) {
                    // 忽略
                }
            }
        }
        return null;
    }

    private static Long checkSupplierExists(String supplierCode) {
        try {
            String url = BASE_URL + "/suppliers/search?name=" + URLEncoder.encode(getSupplierNameByCode(supplierCode), "UTF-8");
            String response = sendGetRequestRaw(url);
            Integer code = extractCodeFromResponse(response);
            if (code != null && code == 200) {
                return extractIdFromResponse(response);
            }
        } catch (Exception e) {
            if (DEBUG) {
                System.err.println("    [DEBUG] Check supplier error: " + e.getMessage());
            }
        }
        return null;
    }

    private static String getSupplierNameByCode(String code) {
        switch (code) {
            case "SUP-SPARK-001": return "电装配件专营店";
            case "SUP-SPARK-002": return "博世配件旗舰店";
            case "SUP-SPARK-003": return "电气配件专营店";
            default: return code;
        }
    }

    private static Map<String, Long> createOrUpdateSuppliers() {
        Map<String, Long> supplierIds = new LinkedHashMap<>();

        // 供应商1: 电装配件专营店
        Map<String, Object> supplierData1 = new HashMap<>();
        supplierData1.put("supplierCode", "SUP-SPARK-001");
        supplierData1.put("name", "电装配件专营店");
        supplierData1.put("contactPerson", "田中太郎");
        supplierData1.put("phone", "021-88880001");
        supplierData1.put("email", "denso@motorparts.com");
        supplierData1.put("address", "上海市嘉定区安亭镇汽车城博园路1001号");
        supplierData1.put("creditRating", "A");
        supplierData1.put("status", 1);

        Long id1 = createOrUpdateSupplier(supplierData1, "DENSO");
        supplierIds.put("DENSO", id1);

        // 供应商2: 博世配件旗舰店
        Map<String, Object> supplierData2 = new HashMap<>();
        supplierData2.put("supplierCode", "SUP-SPARK-002");
        supplierData2.put("name", "博世配件旗舰店");
        supplierData2.put("contactPerson", "Hans Mueller");
        supplierData2.put("phone", "021-88880002");
        supplierData2.put("email", "bosch@motorparts.com");
        supplierData2.put("address", "上海市浦东新区张江高科技园区碧波路690号");
        supplierData2.put("creditRating", "A");
        supplierData2.put("status", 1);

        Long id2 = createOrUpdateSupplier(supplierData2, "BOSCH");
        supplierIds.put("BOSCH", id2);

        // 供应商3: 电气配件专营店
        Map<String, Object> supplierData3 = new HashMap<>();
        supplierData3.put("supplierCode", "SUP-SPARK-003");
        supplierData3.put("name", "电气配件专营店");
        supplierData3.put("contactPerson", "山本健二");
        supplierData3.put("phone", "021-88880003");
        supplierData3.put("email", "ngk@motorparts.com");
        supplierData3.put("address", "上海市静安区南京西路1788号国际中心2001室");
        supplierData3.put("creditRating", "A");
        supplierData3.put("status", 1);

        Long id3 = createOrUpdateSupplier(supplierData3, "NGK");
        supplierIds.put("NGK", id3);

        return supplierIds;
    }

    private static Long createOrUpdateSupplier(Map<String, Object> supplierData, String displayName) {
        String supplierCode = (String) supplierData.get("supplierCode");
        try {
            Long existingId = checkSupplierExists(supplierCode);
            if (existingId != null) {
                String url = BASE_URL + "/suppliers/update/" + existingId;
                String jsonBody = toJson(supplierData);
                String response = sendPutRequestRaw(url, jsonBody);
                Integer code = extractCodeFromResponse(response);
                if (code != null && code == 200) {
                    System.out.println("    [UPDATE] 更新供应商[" + displayName + "] - ID: " + existingId);
                    return existingId;
                } else {
                    System.err.println("    [WARN] 更新供应商失败: " + response);
                }
            } else {
                String url = BASE_URL + "/suppliers/create";
                String jsonBody = toJson(supplierData);
                String response = sendPostRequestRaw(url, jsonBody);
                Integer code = extractCodeFromResponse(response);
                if (code != null && code == 200) {
                    Long id = extractIdFromResponse(response);
                    System.out.println("    [CREATE] 创建供应商[" + displayName + "] - ID: " + id);
                    return id;
                } else {
                    System.err.println("    [WARN] 创建供应商失败: " + response);
                }
            }
        } catch (Exception e) {
            System.err.println("    [ERROR] 处理供应商[" + displayName + "]失败: " + e.getMessage());
        }
        return null;
    }

    private static Map<String, Long> createOrUpdateParts(Map<String, Long> supplierIds) {
        Map<String, Long> partIds = new LinkedHashMap<>();

        // 零件1: DENSO U27ETR
        Map<String, Object> partData1 = new HashMap<>();
        partData1.put("partCode", "SPARK-DENSO-U27ETR");
        partData1.put("name", "电装DENSO火花塞 U27ETR");
        partData1.put("model", "U27ETR");
        partData1.put("specification", "M10×1.0, 0.8mm间隙, 铱金材质, 热值27");
        partData1.put("unit", "个");
        partData1.put("purchasePrice", 32.00);
        partData1.put("suggestedRetailPrice", 38.00);
        partData1.put("stockWarningValue", 20);
        partData1.put("supplierId", supplierIds.get("DENSO"));
        partData1.put("category", "电气类");
        partData1.put("description", "电装DENSO U27ETR摩托车火花塞，专为踏板车设计，采用U型槽技术和锥形电极，燃油经济性好，省油5-10%，冷车启动无忧。适用于本田CG125/雅马哈巧格125/铃木UY125等车型。");

        Long id1 = createOrUpdatePart(partData1, "电装U27ETR");
        if (id1 != null) partIds.put("DENSO", id1);

        // 零件2: BOSCH FR7DC+
        Map<String, Object> partData2 = new HashMap<>();
        partData2.put("partCode", "SPARK-BOSCH-FR7DC");
        partData2.put("name", "博世BOSCH火花塞 FR7DC+");
        partData2.put("model", "FR7DC+");
        partData2.put("specification", "M12×1.25, 0.9mm间隙, 铂金材质, 热值7");
        partData2.put("unit", "个");
        partData2.put("purchasePrice", 40.00);
        partData2.put("suggestedRetailPrice", 48.00);
        partData2.put("stockWarningValue", 20);
        partData2.put("supplierId", supplierIds.get("BOSCH"));
        partData2.put("category", "电气类");
        partData2.put("description", "博世BOSCH FR7DC+铂金火花塞，高性能摩托车专用，采用铂金中心电极技术，点火性能稳定，火焰传播均匀，减少积碳生成，使用寿命长。适用于本田CB400/雅马哈MT-07/宝马F750GS等中大排量车型。");

        Long id2 = createOrUpdatePart(partData2, "博世FR7DC+");
        if (id2 != null) partIds.put("BOSCH", id2);

        // 零件3: NGK CR9EIX
        Map<String, Object> partData3 = new HashMap<>();
        partData3.put("partCode", "SPARK-NGK-CR9EIX");
        partData3.put("name", "NGK铱金火花塞 Iridium IX CR9EIX");
        partData3.put("model", "CR9EIX");
        partData3.put("specification", "M10×1.0, 0.9mm间隙, 铱金材质, 热值9");
        partData3.put("unit", "个");
        partData3.put("purchasePrice", 58.00);
        partData3.put("suggestedRetailPrice", 68.00);
        partData3.put("stockWarningValue", 20);
        partData3.put("supplierId", supplierIds.get("NGK"));
        partData3.put("category", "电气类");
        partData3.put("description", "NGK CR9EIX Iridium IX火花塞，日本原装进口，0.9mm超细铱金中心电极设计，降低点火电压需求，提高点火可靠性。U型槽设计提高点火能量，省油效果明显约5-15%，使用寿命是普通火花塞的2-3倍。适用于本田CBR600RR/雅马哈YZF-R6/铃木GSX-R600等高性能摩托车。");

        Long id3 = createOrUpdatePart(partData3, "NGK CR9EIX");
        if (id3 != null) partIds.put("NGK", id3);

        return partIds;
    }

    private static Long createOrUpdatePart(Map<String, Object> partData, String displayName) {
        String partCode = (String) partData.get("partCode");
        try {
            String searchUrl = BASE_URL + "/parts/search?name=" + URLEncoder.encode((String) partData.get("name"), "UTF-8");
            String searchResponse = sendGetRequestRaw(searchUrl);
            Long existingId = null;
            Integer searchCode = extractCodeFromResponse(searchResponse);
            if (searchCode != null && searchCode == 200) {
                existingId = extractIdFromResponse(searchResponse);
            }

            if (existingId != null) {
                String url = BASE_URL + "/parts/update/" + existingId;
                String jsonBody = toJson(partData);
                String response = sendPutRequestRaw(url, jsonBody);
                Integer code = extractCodeFromResponse(response);
                if (code != null && code == 200) {
                    System.out.println("    [UPDATE] 更新零部件[" + displayName + "] - ID: " + existingId);
                    return existingId;
                } else {
                    System.err.println("    [WARN] 更新零部件失败: " + response);
                }
            } else {
                String url = BASE_URL + "/parts/create";
                String jsonBody = toJson(partData);
                String response = sendPostRequestRaw(url, jsonBody);
                Integer code = extractCodeFromResponse(response);
                if (code != null && code == 200) {
                    Long id = extractIdFromResponse(response);
                    System.out.println("    [CREATE] 创建零部件[" + displayName + "] - ID: " + id);
                    return id;
                } else {
                    System.err.println("    [WARN] 创建零部件失败: " + response);
                }
            }
        } catch (Exception e) {
            System.err.println("    [ERROR] 处理零部件[" + displayName + "]失败: " + e.getMessage());
        }
        return null;
    }

    private static void createInboundRecords(Map<String, Long> partIds) {
        for (Map.Entry<String, Long> entry : partIds.entrySet()) {
            String partName = entry.getKey();
            Long partId = entry.getValue();
            if (checkInventoryExists(partId)) {
                System.out.println("    [SKIP] 库存记录已存在[" + partName + "], 跳过入库");
            } else {
                int quantity = 100 + random.nextInt(100);
                String warehouseLocation = "C区-3号库";
                inbound(partId, quantity, warehouseLocation);
                System.out.println("    [CREATE] 创建入库记录[" + partName + "]: 数量=" + quantity + ", 仓库=" + warehouseLocation);
            }
        }
    }

    private static boolean checkInventoryExists(Long partId) {
        try {
            String partName = getPartNameById(partId);
            String url = BASE_URL + "/inventory/page?current=1&size=10&partName=" + URLEncoder.encode(partName, "UTF-8");
            String response = sendGetRequestRaw(url);
            Integer code = extractCodeFromResponse(response);
            if (code != null && code == 200) {
                return !response.contains("\"records\":[]");
            }
        } catch (Exception e) {
            if (DEBUG) {
                System.err.println("    [DEBUG] Check inventory error: " + e.getMessage());
            }
        }
        return false;
    }

    private static String getPartNameById(Long partId) {
        try {
            String url = BASE_URL + "/parts/get/" + partId;
            String response = sendGetRequestRaw(url);
            Integer code = extractCodeFromResponse(response);
            if (code != null && code == 200) {
                int nameIndex = response.indexOf("\"name\":\"");
                if (nameIndex != -1) {
                    int start = nameIndex + 8;
                    int end = response.indexOf("\"", start);
                    if (end != -1) {
                        return response.substring(start, end);
                    }
                }
            }
        } catch (Exception e) {
            // 忽略
        }
        return "";
    }

    private static void inbound(Long partId, int quantity, String warehouseLocation) {
        try {
            String encodedLocation = URLEncoder.encode(warehouseLocation, "UTF-8");
            String url = BASE_URL + "/inventory/inbound?partId=" + partId + "&quantity=" + quantity + "&warehouseLocation=" + encodedLocation;
            String response = sendPostRequestRaw(url, "");
            Integer code = extractCodeFromResponse(response);
            if (code == null || code != 200) {
                System.err.println("    [WARN] 入库操作返回: " + response);
            }
        } catch (Exception e) {
            System.err.println("    [WARN] 入库操作失败: " + e.getMessage());
        }
    }

    private static void createHistoricalOrders(Map<String, Long> partIds, Map<String, Long> supplierIds) {
        int totalOrders = 0;

        System.out.println("\n    --- 2024年订单 ---");
        int orderIndex2024 = 1;
        for (int month = 1; month <= 12; month++) {
            int ordersPerMonth = 2 + random.nextInt(3);
            for (int i = 0; i < ordersPerMonth; i++) {
                int status = getRandomStatus2024(orderIndex2024);
                boolean success = createOrder(partIds, 2024, month, orderIndex2024, status);
                if (success) {
                    orderIndex2024++;
                    totalOrders++;
                }
            }
        }

        System.out.println("\n    --- 2025年订单 ---");
        int orderIndex2025 = 1;
        for (int month = 1; month <= 5; month++) {
            int ordersPerMonth = 3 + random.nextInt(3);
            for (int i = 0; i < ordersPerMonth; i++) {
                int status;
                if (month < 5) {
                    status = 4;
                } else {
                    status = getRandomStatus(new int[]{1, 2, 3, 4}, new int[]{10, 20, 30, 40});
                }
                boolean success = createOrder(partIds, 2025, month, orderIndex2025, status);
                if (success) {
                    orderIndex2025++;
                    totalOrders++;
                }
            }
        }

        System.out.println("\n    共创建订单: " + totalOrders + " 个");
    }

    private static int getRandomStatus2024(int orderIndex) {
        if (orderIndex <= 3) return 1;
        if (orderIndex <= 8) return 2;
        if (orderIndex <= 12) return 3;
        return 4;
    }

    private static int getRandomStatus(int[] statuses, int[] weights) {
        int totalWeight = 0;
        for (int weight : weights) {
            totalWeight += weight;
        }
        int randomValue = random.nextInt(totalWeight);
        int cumulativeWeight = 0;
        for (int i = 0; i < statuses.length; i++) {
            cumulativeWeight += weights[i];
            if (randomValue < cumulativeWeight) {
                return statuses[i];
            }
        }
        return statuses[statuses.length - 1];
    }

    private static boolean createOrder(Map<String, Long> partIds, int year, int month, int orderIndex, int status) {
        try {
            int day = 1 + random.nextInt(28);
            LocalDate orderDate = LocalDate.of(year, month, day);
            LocalDateTime orderTime = orderDate.atTime(8 + random.nextInt(10), random.nextInt(60));
            LocalDate expectedDeliveryDate = orderDate.plusDays(7 + random.nextInt(7));

            long timestamp = System.currentTimeMillis() % 10000;
            String orderNumber = String.format("PO%s%02d%04d-%d", year, month, orderIndex, timestamp);

            List<Map.Entry<String, Long>> partList = new ArrayList<>(partIds.entrySet());
            Collections.shuffle(partList);
            int itemCount = 1 + random.nextInt(Math.min(3, partList.size()));

            List<Map<String, Object>> orderDetails = new ArrayList<>();
            BigDecimal totalAmount = BigDecimal.ZERO;
            Set<String> usedParts = new HashSet<>();

            for (int i = 0; i < itemCount; i++) {
                Map.Entry<String, Long> partEntry = partList.get(i);
                String partName = partEntry.getKey();
                Long partId = partEntry.getValue();

                if (usedParts.contains(partName)) continue;
                usedParts.add(partName);

                BigDecimal unitPrice = getUnitPrice(partName);
                int quantity = 10 + random.nextInt(30);
                BigDecimal subtotal = unitPrice.multiply(BigDecimal.valueOf(quantity));
                totalAmount = totalAmount.add(subtotal);

                Map<String, Object> detail = new HashMap<>();
                detail.put("orderId", 0);
                detail.put("partId", partId);
                detail.put("quantity", quantity);
                detail.put("unitPrice", unitPrice.doubleValue());
                detail.put("subtotal", subtotal.doubleValue());
                detail.put("remark", partName + "火花塞采购");
                orderDetails.add(detail);
            }

            Map<String, Object> order = new HashMap<>();
            order.put("orderNumber", orderNumber);
            order.put("totalAmount", totalAmount.doubleValue());
            order.put("status", status);
            // 使用 yyyy-MM-dd'T'HH:mm:ss.SSS 格式
            order.put("orderTime", orderTime.format(DATETIME_FORMATTER));
            order.put("expectedDeliveryDate", expectedDeliveryDate.format(DATE_FORMATTER));

            if (status == 4) {
                LocalDate actualDate = expectedDeliveryDate.plusDays(random.nextInt(5) - 2);
                order.put("actualDeliveryDate", actualDate.format(DATE_FORMATTER));
            }

            order.put("createdBy", 1L);
            order.put("remark", String.format("%d年%d月火花塞常规采购订单", year, month));
            order.put("orderDetail", orderDetails);

            createOrderViaApi(order);
            System.out.println("    [OK] 订单[" + orderNumber + "]: 状态=" + getStatusName(status) + ", 金额=" + totalAmount + "元, 零件数=" + orderDetails.size());

            return true;
        } catch (Exception e) {
            System.err.println("    [FAIL] 创建订单失败: " + e.getMessage());
            return false;
        }
    }

    private static String getStatusName(int status) {
        switch (status) {
            case 1: return "待审核";
            case 2: return "已审核";
            case 3: return "采购中";
            case 4: return "已入库";
            case 5: return "已取消";
            default: return "未知";
        }
    }

    private static BigDecimal getUnitPrice(String partName) {
        switch (partName) {
            case "DENSO": return new BigDecimal("32.00");
            case "BOSCH": return new BigDecimal("40.00");
            case "NGK": return new BigDecimal("58.00");
            default: return new BigDecimal("35.00");
        }
    }

    private static void createOrderViaApi(Map<String, Object> order) throws IOException, InterruptedException {
        String jsonBody = toJson(order);
        String url = BASE_URL + "/orders/create";
        String response = sendPostRequestRaw(url, jsonBody);
        Integer code = extractCodeFromResponse(response);
        if (code == null || code != 200) {
            throw new RuntimeException("API返回错误: " + response);
        }
    }

    private static void printSummary(Map<String, Long> partIds, Map<String, Long> supplierIds) {
        System.out.println("\n==============================================");
        System.out.println("                  数据摘要");
        System.out.println("==============================================");
        System.out.println();
        System.out.println("【供应商】");
        for (Map.Entry<String, Long> entry : supplierIds.entrySet()) {
            System.out.println("  - " + entry.getKey() + " (ID: " + entry.getValue() + ")");
        }
        System.out.println();
        System.out.println("【零部件】");
        for (Map.Entry<String, Long> entry : partIds.entrySet()) {
            System.out.println("  - " + entry.getKey() + " (ID: " + entry.getValue() + ")");
        }
        System.out.println();
        System.out.println("【入库库存】");
        for (String partName : partIds.keySet()) {
            int qty = 100 + random.nextInt(100);
            System.out.println("  - " + partName + ": " + qty + " 件 (C区-3号库)");
        }
        System.out.println();
        System.out.println("【订单数据】");
        System.out.println("  - 2024年: 约36个订单 (1-12月)");
        System.out.println("  - 2025年: 约20个订单 (1-5月)");
        System.out.println();
        System.out.println("==============================================");
    }
}
