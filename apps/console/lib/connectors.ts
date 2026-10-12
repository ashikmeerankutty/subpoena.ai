// Catalog of historical-data connectors (prototype). Only the BigQuery demo dataset is live;
// the rest show the setup a bank would go through and are labelled as previews in the UI.

export type Category = "Warehouse" | "Storage & files" | "Customer data" | "CRM" | "Core banking & payments" | "Streaming" | "Enrichment";

export const CATEGORIES: Category[] = [
  "Warehouse", "Storage & files", "Customer data", "CRM", "Core banking & payments", "Streaming", "Enrichment",
];

/** What a connector contributes to the courtroom's picture of a cardholder. */
export type DataKind = "Transactions" | "Fraud labels" | "Profiles & phone" | "Devices & IPs" | "Geo" | "Travel notices" | "Entity links";

export interface Field { key: string; label: string; placeholder?: string; help?: string; secret?: boolean }

export interface Connector {
  id: string;
  name: string;
  category: Category;
  initials: string;
  color: string;
  tagline: string;
  brings: DataKind[];
  sync: "Streaming" | "Scheduled" | "One-off";
  oauth?: string; // label of the sign-in button, when the source authorises with OAuth
  fields: Field[];
  mapping: [string, string][]; // [source field, Subpoena.ai field]
  live?: { summary: string; detail: string };
}

const TXN_MAPPING: [string, string][] = [
  ["TXN_ID", "transaction_id"], ["CUSTOMER_ID", "user_id"], ["AMOUNT", "amount"], ["CURRENCY", "currency"],
  ["CHANNEL", "type"], ["TXN_TS", "occurred_at"], ["MERCHANT_NAME", "merchant.name"], ["MCC", "merchant.mcc"],
  ["MERCHANT_COUNTRY", "merchant.country"], ["IP_ADDRESS", "metadata.ip_address"],
  ["DEVICE_ID", "metadata.device_fingerprint"], ["CHARGEBACK_FLAG", "label"],
];

const warehouse = (extra: Field[]): Field[] => [
  ...extra,
  { key: "table", label: "Transactions table or view", placeholder: "FRAUD.TRANSACTIONS_90D" },
  { key: "labels", label: "Chargebacks / confirmed-fraud table (optional)", placeholder: "FRAUD.CHARGEBACKS" },
];

export const CONNECTORS: Connector[] = [
  {
    id: "bigquery", name: "BigQuery", category: "Warehouse", initials: "BQ", color: "#4285f4",
    tagline: "Transactions, customers and the entity graph, read in place by the agents.",
    brings: ["Transactions", "Profiles & phone", "Devices & IPs", "Entity links"], sync: "Scheduled",
    fields: warehouse([{ key: "project", label: "Project", placeholder: "bank-fraud-prod" }, { key: "dataset", label: "Dataset", placeholder: "fraud" }]),
    mapping: TXN_MAPPING,
    live: { summary: "Demo dataset · 23 customers · 5,134 transactions · 90 days",
      detail: "The synthetic dataset the deployed agents read today: baselines, transaction history and a mule-ring graph." },
  },
  {
    id: "snowflake", name: "Snowflake", category: "Warehouse", initials: "SF", color: "#29b5e8",
    tagline: "Secure-share or query the bank's transaction history without copying it.",
    brings: ["Transactions", "Fraud labels", "Devices & IPs"], sync: "Scheduled",
    fields: warehouse([
      { key: "account", label: "Account identifier", placeholder: "acme-bank.eu-west-1" },
      { key: "warehouse", label: "Warehouse", placeholder: "FRAUD_WH" },
      { key: "database", label: "Database", placeholder: "RISK" },
      { key: "key", label: "Private key (key-pair auth)", placeholder: "-----BEGIN PRIVATE KEY-----", secret: true },
    ]),
    mapping: TXN_MAPPING,
  },
  {
    id: "databricks", name: "Databricks", category: "Warehouse", initials: "DB", color: "#ff3621",
    tagline: "Delta tables of card activity through Unity Catalog.",
    brings: ["Transactions", "Fraud labels"], sync: "Scheduled",
    fields: warehouse([
      { key: "host", label: "Workspace URL", placeholder: "https://acme.cloud.databricks.com" },
      { key: "http_path", label: "SQL warehouse HTTP path", placeholder: "/sql/1.0/warehouses/…" },
      { key: "token", label: "Access token", secret: true },
    ]),
    mapping: TXN_MAPPING,
  },
  {
    id: "redshift", name: "Amazon Redshift", category: "Warehouse", initials: "RS", color: "#8c4fff",
    tagline: "Historical transactions from the bank's AWS warehouse.",
    brings: ["Transactions", "Fraud labels"], sync: "Scheduled",
    fields: warehouse([
      { key: "endpoint", label: "Cluster endpoint", placeholder: "fraud.abc123.us-east-1.redshift.amazonaws.com:5439" },
      { key: "role", label: "IAM role ARN", placeholder: "arn:aws:iam::…:role/subpoena-reader" },
    ]),
    mapping: TXN_MAPPING,
  },
  {
    id: "gcs", name: "Cloud Storage", category: "Storage & files", initials: "GCS", color: "#34a853",
    tagline: "Drop CSV or Parquet exports in a bucket; new files are picked up automatically.",
    brings: ["Transactions", "Fraud labels"], sync: "Scheduled",
    fields: [{ key: "uri", label: "Bucket and prefix", placeholder: "gs://acme-fraud-exports/transactions/" },
      { key: "format", label: "Format", placeholder: "CSV, JSONL or Parquet" }],
    mapping: TXN_MAPPING,
  },
  {
    id: "s3", name: "Amazon S3", category: "Storage & files", initials: "S3", color: "#e25444",
    tagline: "Batch exports from an S3 bucket, read with a cross-account role.",
    brings: ["Transactions", "Fraud labels"], sync: "Scheduled",
    fields: [{ key: "uri", label: "Bucket and prefix", placeholder: "s3://acme-fraud-exports/transactions/" },
      { key: "role", label: "IAM role ARN", placeholder: "arn:aws:iam::…:role/subpoena-reader" }],
    mapping: TXN_MAPPING,
  },
  {
    id: "sftp", name: "SFTP", category: "Storage & files", initials: "FTP", color: "#4b5671",
    tagline: "Nightly files from core systems that can only push over SFTP.",
    brings: ["Transactions", "Fraud labels"], sync: "Scheduled",
    fields: [{ key: "host", label: "Host", placeholder: "sftp.acme-bank.com" }, { key: "path", label: "Directory", placeholder: "/outbound/fraud/" },
      { key: "key", label: "SSH private key", secret: true }],
    mapping: TXN_MAPPING,
  },
  {
    id: "csv", name: "CSV upload", category: "Storage & files", initials: "CSV", color: "#121c2d",
    tagline: "One-off backfill: upload 90 days of history to try Subpoena.ai on your own data.",
    brings: ["Transactions", "Fraud labels"], sync: "One-off",
    fields: [{ key: "file", label: "File", placeholder: "transactions_90d.csv", help: "Up to 30 MB. One row per transaction; a label column marks confirmed fraud." }],
    mapping: TXN_MAPPING,
  },
  {
    id: "segment", name: "Segment", category: "Customer data", initials: "SG", color: "#52bd94",
    tagline: "App and web sessions: the devices, IPs and locations each customer normally uses.",
    brings: ["Devices & IPs", "Geo"], sync: "Streaming",
    fields: [{ key: "endpoint", label: "Subpoena.ai destination endpoint", placeholder: "https://api.subpoena.ai/v1/connectors/segment",
      help: "Add Subpoena.ai as a destination in Segment and paste this endpoint with the signing key below." },
      { key: "key", label: "Shared signing key", secret: true },
      { key: "events", label: "Events to forward", placeholder: "Signed In, Device Added, Payment Started" }],
    mapping: [["userId", "user_id"], ["context.ip", "metadata.ip_address"], ["context.device.id", "metadata.device_fingerprint"],
      ["context.location.country", "home.country"], ["context.timezone", "utc_offset_hours"], ["timestamp", "occurred_at"]],
  },
  {
    id: "mparticle", name: "mParticle", category: "Customer data", initials: "mP", color: "#2d8cff",
    tagline: "Mobile banking app events and device identities.",
    brings: ["Devices & IPs", "Geo"], sync: "Streaming",
    fields: [{ key: "key", label: "Server-to-server API key", secret: true }, { key: "secret", label: "API secret", secret: true }],
    mapping: [["customer_id", "user_id"], ["ip", "metadata.ip_address"], ["device_info.device_application_stamp", "metadata.device_fingerprint"]],
  },
  {
    id: "salesforce", name: "Salesforce Financial Services Cloud", category: "CRM", initials: "SF", color: "#00a1e0",
    tagline: "Customer contact details, travel notices and fraud cases logged by agents.",
    brings: ["Profiles & phone", "Travel notices", "Fraud labels"], sync: "Scheduled", oauth: "Sign in with Salesforce",
    fields: [{ key: "objects", label: "Objects to sync", placeholder: "Contact, FinServ__FinancialAccount__c, Case" }],
    mapping: [["Contact.Customer_Id__c", "user_id"], ["Contact.MobilePhone", "phone"], ["Contact.MailingCountry", "home.country"],
      ["Case.Type = 'Travel Notice'", "travel_notice"], ["Case.Type = 'Fraud Claim'", "label"]],
  },
  {
    id: "dynamics", name: "Microsoft Dynamics 365", category: "CRM", initials: "D365", color: "#0b53ce",
    tagline: "Customer records and contact preferences from Dynamics.",
    brings: ["Profiles & phone", "Travel notices"], sync: "Scheduled", oauth: "Sign in with Microsoft",
    fields: [{ key: "org", label: "Organisation URL", placeholder: "https://acme.crm.dynamics.com" }],
    mapping: [["contact.customerid", "user_id"], ["contact.mobilephone", "phone"], ["contact.address1_country", "home.country"]],
  },
  {
    id: "fiserv", name: "Fiserv", category: "Core banking & payments", initials: "FI", color: "#ff6600",
    tagline: "Card authorisations and chargebacks from the processor.",
    brings: ["Transactions", "Fraud labels"], sync: "Scheduled",
    fields: [{ key: "client", label: "Client ID", placeholder: "issued by Fiserv" }, { key: "secret", label: "Client secret", secret: true }],
    mapping: TXN_MAPPING,
  },
  {
    id: "temenos", name: "Temenos", category: "Core banking & payments", initials: "TM", color: "#1f2a6b",
    tagline: "Accounts, payees and transfers from the core banking system.",
    brings: ["Transactions", "Entity links"], sync: "Scheduled",
    fields: [{ key: "url", label: "API base URL", placeholder: "https://core.acme-bank.com/api/v1" }, { key: "token", label: "API token", secret: true }],
    mapping: [["arrangementId", "user_id"], ["transactionReference", "transaction_id"], ["amount", "amount"], ["counterparty.accountId", "payee"]],
  },
  {
    id: "stripe", name: "Stripe", category: "Core banking & payments", initials: "ST", color: "#635bff",
    tagline: "Charges, disputes and Radar outcomes for card-not-present payments.",
    brings: ["Transactions", "Fraud labels", "Devices & IPs"], sync: "Streaming", oauth: "Connect with Stripe",
    fields: [{ key: "events", label: "Webhook events", placeholder: "charge.succeeded, charge.dispute.created" }],
    mapping: [["charge.id", "transaction_id"], ["charge.customer", "user_id"], ["charge.amount", "amount"],
      ["charge.payment_method_details.card.network", "type"], ["dispute.reason = fraudulent", "label"]],
  },
  {
    id: "adyen", name: "Adyen", category: "Core banking & payments", initials: "AD", color: "#0abf53",
    tagline: "Payment notifications and chargebacks across acquiring markets.",
    brings: ["Transactions", "Fraud labels"], sync: "Streaming",
    fields: [{ key: "merchant", label: "Merchant account", placeholder: "AcmeBankECOM" }, { key: "hmac", label: "HMAC key", secret: true }],
    mapping: [["pspReference", "transaction_id"], ["shopperReference", "user_id"], ["amount.value", "amount"], ["eventCode = CHARGEBACK", "label"]],
  },
  {
    id: "kafka", name: "Kafka / Confluent", category: "Streaming", initials: "K", color: "#231f20",
    tagline: "Stream every authorisation as it happens to keep baselines current.",
    brings: ["Transactions", "Devices & IPs"], sync: "Streaming",
    fields: [{ key: "brokers", label: "Bootstrap servers", placeholder: "pkc-xxxx.us-central1.gcp.confluent.cloud:9092" },
      { key: "topic", label: "Topic", placeholder: "card.authorisations" }, { key: "secret", label: "API secret", secret: true }],
    mapping: TXN_MAPPING,
  },
  {
    id: "pubsub", name: "Pub/Sub", category: "Streaming", initials: "PS", color: "#1a73e8",
    tagline: "Subscribe to the bank's transaction topic on Google Cloud.",
    brings: ["Transactions"], sync: "Streaming",
    fields: [{ key: "subscription", label: "Subscription", placeholder: "projects/acme-bank/subscriptions/subpoena-history" }],
    mapping: TXN_MAPPING,
  },
  {
    id: "maxmind", name: "MaxMind GeoIP2", category: "Enrichment", initials: "MM", color: "#1d6fa5",
    tagline: "City-level location, ISP and proxy detection for every IP the agents see.",
    brings: ["Geo", "Devices & IPs"], sync: "Scheduled",
    fields: [{ key: "account", label: "Account ID" }, { key: "license", label: "License key", secret: true }],
    mapping: [["ip", "metadata.ip_address"], ["city / country / location", "ip_geo"], ["traits.is_anonymous_proxy", "is_vpn_or_proxy"]],
  },
  {
    id: "ipinfo", name: "IPinfo", category: "Enrichment", initials: "IP", color: "#3e3e8e",
    tagline: "ASN type and privacy detection (VPN, hosting, Tor) for IP reputation.",
    brings: ["Geo", "Devices & IPs"], sync: "Scheduled",
    fields: [{ key: "token", label: "Access token", secret: true }],
    mapping: [["ip", "metadata.ip_address"], ["asn.type", "asn_type"], ["privacy.vpn", "is_vpn_or_proxy"]],
  },
];
