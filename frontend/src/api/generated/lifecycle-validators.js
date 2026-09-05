// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateHistoryImportJobResponse = validate53;
const schema20 = {"properties":{"created_at":{"title":"Created At","type":"number"},"detected_kind":{"enum":["document","chat","mixed"],"title":"Detected Kind","type":"string"},"error_code":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Error Code"},"imported_count":{"title":"Imported Count","type":"integer"},"importer_id":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Importer Id"},"importer_plugin_id":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Importer Plugin Id"},"included_source_ids":{"items":{"type":"string"},"title":"Included Source Ids","type":"array"},"job_id":{"title":"Job Id","type":"string"},"meaningful_records":{"title":"Meaningful Records","type":"integer"},"participants":{"items":{"$ref":"#/components/schemas/HistoryImportParticipantResponse"},"title":"Participants","type":"array"},"preview_records":{"items":{"$ref":"#/components/schemas/HistoryImportRecordPreviewResponse"},"title":"Preview Records","type":"array"},"projected_count":{"title":"Projected Count","type":"integer"},"quick_imported_count":{"title":"Quick Imported Count","type":"integer"},"quick_max_records":{"title":"Quick Max Records","type":"integer"},"quick_ready":{"title":"Quick Ready","type":"boolean"},"quick_target_records":{"title":"Quick Target Records","type":"integer"},"self_participant_ids":{"items":{"type":"string"},"title":"Self Participant Ids","type":"array"},"source_ids":{"items":{"type":"string"},"title":"Source Ids","type":"array"},"source_type":{"title":"Source Type","type":"string"},"sources":{"items":{"$ref":"#/components/schemas/HistoryImportSourceSummaryResponse"},"title":"Sources","type":"array"},"status":{"enum":["preview_ready","running","ready","completed","failed","deleted"],"title":"Status","type":"string"},"total_records":{"title":"Total Records","type":"integer"},"updated_at":{"title":"Updated At","type":"number"},"warning_summary":{"$ref":"#/components/schemas/HistoryImportWarningSummaryResponse"}},"required":["job_id","source_type","source_ids","included_source_ids","detected_kind","status","total_records","meaningful_records","quick_target_records","quick_max_records","quick_imported_count","imported_count","projected_count","self_participant_ids","importer_plugin_id","importer_id","warning_summary","quick_ready","error_code","created_at","updated_at","participants","sources","preview_records"],"title":"HistoryImportJobResponse","type":"object"};
const schema21 = {"properties":{"display_name":{"title":"Display Name","type":"string"},"is_document_author":{"title":"Is Document Author","type":"boolean"},"meaningful_count":{"title":"Meaningful Count","type":"integer"},"message_count":{"title":"Message Count","type":"integer"},"participant_id":{"title":"Participant Id","type":"string"},"sample":{"title":"Sample","type":"string"}},"required":["participant_id","display_name","is_document_author","message_count","meaningful_count","sample"],"title":"HistoryImportParticipantResponse","type":"object"};

function validate54(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate54.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.participant_id === undefined) && (missing0 = "participant_id")) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.is_document_author === undefined) && (missing0 = "is_document_author"))) || ((data.message_count === undefined) && (missing0 = "message_count"))) || ((data.meaningful_count === undefined) && (missing0 = "meaningful_count"))) || ((data.sample === undefined) && (missing0 = "sample"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.display_name !== undefined){
const _errs1 = errors;
if(typeof data.display_name !== "string"){
validate54.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_document_author !== undefined){
const _errs3 = errors;
if(typeof data.is_document_author !== "boolean"){
validate54.errors = [{instancePath:instancePath+"/is_document_author",schemaPath:"#/properties/is_document_author/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.meaningful_count !== undefined){
let data2 = data.meaningful_count;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate54.errors = [{instancePath:instancePath+"/meaningful_count",schemaPath:"#/properties/meaningful_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_count !== undefined){
let data3 = data.message_count;
const _errs7 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate54.errors = [{instancePath:instancePath+"/message_count",schemaPath:"#/properties/message_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.participant_id !== undefined){
const _errs9 = errors;
if(typeof data.participant_id !== "string"){
validate54.errors = [{instancePath:instancePath+"/participant_id",schemaPath:"#/properties/participant_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sample !== undefined){
const _errs11 = errors;
if(typeof data.sample !== "string"){
validate54.errors = [{instancePath:instancePath+"/sample",schemaPath:"#/properties/sample/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":{"display_name":true,"is_document_author":true,"meaningful_count":true,"message_count":true,"participant_id":true,"sample":true},"dynamicProps":false,"dynamicItems":false};

const schema22 = {"properties":{"content":{"title":"Content","type":"string"},"event_at":{"title":"Event At","type":"number"},"is_document_author":{"title":"Is Document Author","type":"boolean"},"session_id":{"title":"Session Id","type":"string"},"session_seq":{"title":"Session Seq","type":"integer"},"source_id":{"title":"Source Id","type":"string"},"source_name":{"title":"Source Name","type":"string"},"speaker_id":{"title":"Speaker Id","type":"string"},"speaker_name":{"title":"Speaker Name","type":"string"},"timestamp_confidence":{"title":"Timestamp Confidence","type":"string"}},"required":["source_id","source_name","session_id","session_seq","speaker_id","speaker_name","is_document_author","content","event_at","timestamp_confidence"],"title":"HistoryImportRecordPreviewResponse","type":"object"};

function validate56(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate56.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((data.source_id === undefined) && (missing0 = "source_id")) || ((data.source_name === undefined) && (missing0 = "source_name"))) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.session_seq === undefined) && (missing0 = "session_seq"))) || ((data.speaker_id === undefined) && (missing0 = "speaker_id"))) || ((data.speaker_name === undefined) && (missing0 = "speaker_name"))) || ((data.is_document_author === undefined) && (missing0 = "is_document_author"))) || ((data.content === undefined) && (missing0 = "content"))) || ((data.event_at === undefined) && (missing0 = "event_at"))) || ((data.timestamp_confidence === undefined) && (missing0 = "timestamp_confidence"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.content !== undefined){
const _errs1 = errors;
if(typeof data.content !== "string"){
validate56.errors = [{instancePath:instancePath+"/content",schemaPath:"#/properties/content/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_at !== undefined){
const _errs3 = errors;
if(!(typeof data.event_at == "number")){
validate56.errors = [{instancePath:instancePath+"/event_at",schemaPath:"#/properties/event_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_document_author !== undefined){
const _errs5 = errors;
if(typeof data.is_document_author !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/is_document_author",schemaPath:"#/properties/is_document_author/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs7 = errors;
if(typeof data.session_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_seq !== undefined){
let data4 = data.session_seq;
const _errs9 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate56.errors = [{instancePath:instancePath+"/session_seq",schemaPath:"#/properties/session_seq/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_id !== undefined){
const _errs11 = errors;
if(typeof data.source_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/source_id",schemaPath:"#/properties/source_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_name !== undefined){
const _errs13 = errors;
if(typeof data.source_name !== "string"){
validate56.errors = [{instancePath:instancePath+"/source_name",schemaPath:"#/properties/source_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.speaker_id !== undefined){
const _errs15 = errors;
if(typeof data.speaker_id !== "string"){
validate56.errors = [{instancePath:instancePath+"/speaker_id",schemaPath:"#/properties/speaker_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.speaker_name !== undefined){
const _errs17 = errors;
if(typeof data.speaker_name !== "string"){
validate56.errors = [{instancePath:instancePath+"/speaker_name",schemaPath:"#/properties/speaker_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp_confidence !== undefined){
const _errs19 = errors;
if(typeof data.timestamp_confidence !== "string"){
validate56.errors = [{instancePath:instancePath+"/timestamp_confidence",schemaPath:"#/properties/timestamp_confidence/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":{"content":true,"event_at":true,"is_document_author":true,"session_id":true,"session_seq":true,"source_id":true,"source_name":true,"speaker_id":true,"speaker_name":true,"timestamp_confidence":true},"dynamicProps":false,"dynamicItems":false};

const schema23 = {"properties":{"detected_kind":{"enum":["document","chat","mixed"],"title":"Detected Kind","type":"string"},"first_event_at":{"title":"First Event At","type":"number"},"included":{"title":"Included","type":"boolean"},"last_event_at":{"title":"Last Event At","type":"number"},"meaningful_count":{"title":"Meaningful Count","type":"integer"},"record_count":{"title":"Record Count","type":"integer"},"sample":{"title":"Sample","type":"string"},"source_id":{"title":"Source Id","type":"string"},"source_name":{"title":"Source Name","type":"string"},"timestamp_confidence":{"title":"Timestamp Confidence","type":"string"}},"required":["source_id","source_name","detected_kind","record_count","meaningful_count","first_event_at","last_event_at","timestamp_confidence","sample","included"],"title":"HistoryImportSourceSummaryResponse","type":"object"};

function validate58(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate58.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((data.source_id === undefined) && (missing0 = "source_id")) || ((data.source_name === undefined) && (missing0 = "source_name"))) || ((data.detected_kind === undefined) && (missing0 = "detected_kind"))) || ((data.record_count === undefined) && (missing0 = "record_count"))) || ((data.meaningful_count === undefined) && (missing0 = "meaningful_count"))) || ((data.first_event_at === undefined) && (missing0 = "first_event_at"))) || ((data.last_event_at === undefined) && (missing0 = "last_event_at"))) || ((data.timestamp_confidence === undefined) && (missing0 = "timestamp_confidence"))) || ((data.sample === undefined) && (missing0 = "sample"))) || ((data.included === undefined) && (missing0 = "included"))){
validate58.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.detected_kind !== undefined){
let data0 = data.detected_kind;
const _errs1 = errors;
if(typeof data0 !== "string"){
validate58.errors = [{instancePath:instancePath+"/detected_kind",schemaPath:"#/properties/detected_kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data0 === "document") || (data0 === "chat")) || (data0 === "mixed"))){
validate58.errors = [{instancePath:instancePath+"/detected_kind",schemaPath:"#/properties/detected_kind/enum",keyword:"enum",params:{allowedValues: schema23.properties.detected_kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.first_event_at !== undefined){
const _errs3 = errors;
if(!(typeof data.first_event_at == "number")){
validate58.errors = [{instancePath:instancePath+"/first_event_at",schemaPath:"#/properties/first_event_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.included !== undefined){
const _errs5 = errors;
if(typeof data.included !== "boolean"){
validate58.errors = [{instancePath:instancePath+"/included",schemaPath:"#/properties/included/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_event_at !== undefined){
const _errs7 = errors;
if(!(typeof data.last_event_at == "number")){
validate58.errors = [{instancePath:instancePath+"/last_event_at",schemaPath:"#/properties/last_event_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.meaningful_count !== undefined){
let data4 = data.meaningful_count;
const _errs9 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate58.errors = [{instancePath:instancePath+"/meaningful_count",schemaPath:"#/properties/meaningful_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.record_count !== undefined){
let data5 = data.record_count;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate58.errors = [{instancePath:instancePath+"/record_count",schemaPath:"#/properties/record_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sample !== undefined){
const _errs13 = errors;
if(typeof data.sample !== "string"){
validate58.errors = [{instancePath:instancePath+"/sample",schemaPath:"#/properties/sample/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_id !== undefined){
const _errs15 = errors;
if(typeof data.source_id !== "string"){
validate58.errors = [{instancePath:instancePath+"/source_id",schemaPath:"#/properties/source_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_name !== undefined){
const _errs17 = errors;
if(typeof data.source_name !== "string"){
validate58.errors = [{instancePath:instancePath+"/source_name",schemaPath:"#/properties/source_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp_confidence !== undefined){
const _errs19 = errors;
if(typeof data.timestamp_confidence !== "string"){
validate58.errors = [{instancePath:instancePath+"/timestamp_confidence",schemaPath:"#/properties/timestamp_confidence/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate58.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate58.errors = vErrors;
return errors === 0;
}
validate58.evaluated = {"props":{"detected_kind":true,"first_event_at":true,"included":true,"last_event_at":true,"meaningful_count":true,"record_count":true,"sample":true,"source_id":true,"source_name":true,"timestamp_confidence":true},"dynamicProps":false,"dynamicItems":false};

const schema24 = {"properties":{"codes":{"items":{"type":"string"},"title":"Codes","type":"array"},"total_count":{"title":"Total Count","type":"integer"},"truncated":{"title":"Truncated","type":"boolean"}},"required":["total_count","codes","truncated"],"title":"HistoryImportWarningSummaryResponse","type":"object"};

function validate60(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate60.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.total_count === undefined) && (missing0 = "total_count")) || ((data.codes === undefined) && (missing0 = "codes"))) || ((data.truncated === undefined) && (missing0 = "truncated"))){
validate60.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.codes !== undefined){
let data0 = data.codes;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(typeof data0[i0] !== "string"){
validate60.errors = [{instancePath:instancePath+"/codes/" + i0,schemaPath:"#/properties/codes/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate60.errors = [{instancePath:instancePath+"/codes",schemaPath:"#/properties/codes/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total_count !== undefined){
let data2 = data.total_count;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate60.errors = [{instancePath:instancePath+"/total_count",schemaPath:"#/properties/total_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.truncated !== undefined){
const _errs7 = errors;
if(typeof data.truncated !== "boolean"){
validate60.errors = [{instancePath:instancePath+"/truncated",schemaPath:"#/properties/truncated/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate60.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate60.errors = vErrors;
return errors === 0;
}
validate60.evaluated = {"props":{"codes":true,"total_count":true,"truncated":true},"dynamicProps":false,"dynamicItems":false};


function validate53(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate53.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((((((((((((data.job_id === undefined) && (missing0 = "job_id")) || ((data.source_type === undefined) && (missing0 = "source_type"))) || ((data.source_ids === undefined) && (missing0 = "source_ids"))) || ((data.included_source_ids === undefined) && (missing0 = "included_source_ids"))) || ((data.detected_kind === undefined) && (missing0 = "detected_kind"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.total_records === undefined) && (missing0 = "total_records"))) || ((data.meaningful_records === undefined) && (missing0 = "meaningful_records"))) || ((data.quick_target_records === undefined) && (missing0 = "quick_target_records"))) || ((data.quick_max_records === undefined) && (missing0 = "quick_max_records"))) || ((data.quick_imported_count === undefined) && (missing0 = "quick_imported_count"))) || ((data.imported_count === undefined) && (missing0 = "imported_count"))) || ((data.projected_count === undefined) && (missing0 = "projected_count"))) || ((data.self_participant_ids === undefined) && (missing0 = "self_participant_ids"))) || ((data.importer_plugin_id === undefined) && (missing0 = "importer_plugin_id"))) || ((data.importer_id === undefined) && (missing0 = "importer_id"))) || ((data.warning_summary === undefined) && (missing0 = "warning_summary"))) || ((data.quick_ready === undefined) && (missing0 = "quick_ready"))) || ((data.error_code === undefined) && (missing0 = "error_code"))) || ((data.created_at === undefined) && (missing0 = "created_at"))) || ((data.updated_at === undefined) && (missing0 = "updated_at"))) || ((data.participants === undefined) && (missing0 = "participants"))) || ((data.sources === undefined) && (missing0 = "sources"))) || ((data.preview_records === undefined) && (missing0 = "preview_records"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.created_at !== undefined){
const _errs1 = errors;
if(!(typeof data.created_at == "number")){
validate53.errors = [{instancePath:instancePath+"/created_at",schemaPath:"#/properties/created_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.detected_kind !== undefined){
let data1 = data.detected_kind;
const _errs3 = errors;
if(typeof data1 !== "string"){
validate53.errors = [{instancePath:instancePath+"/detected_kind",schemaPath:"#/properties/detected_kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data1 === "document") || (data1 === "chat")) || (data1 === "mixed"))){
validate53.errors = [{instancePath:instancePath+"/detected_kind",schemaPath:"#/properties/detected_kind/enum",keyword:"enum",params:{allowedValues: schema20.properties.detected_kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error_code !== undefined){
let data2 = data.error_code;
const _errs5 = errors;
const _errs6 = errors;
let valid1 = false;
const _errs7 = errors;
if(typeof data2 !== "string"){
const err0 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs7 === errors;
valid1 = valid1 || _valid0;
const _errs9 = errors;
if(data2 !== null){
const err1 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs9 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs6;
if(vErrors !== null){
if(_errs6){
vErrors.length = _errs6;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.imported_count !== undefined){
let data3 = data.imported_count;
const _errs11 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate53.errors = [{instancePath:instancePath+"/imported_count",schemaPath:"#/properties/imported_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.importer_id !== undefined){
let data4 = data.importer_id;
const _errs13 = errors;
const _errs14 = errors;
let valid2 = false;
const _errs15 = errors;
if(typeof data4 !== "string"){
const err3 = {instancePath:instancePath+"/importer_id",schemaPath:"#/properties/importer_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs15 === errors;
valid2 = valid2 || _valid1;
const _errs17 = errors;
if(data4 !== null){
const err4 = {instancePath:instancePath+"/importer_id",schemaPath:"#/properties/importer_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs17 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/importer_id",schemaPath:"#/properties/importer_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs14;
if(vErrors !== null){
if(_errs14){
vErrors.length = _errs14;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.importer_plugin_id !== undefined){
let data5 = data.importer_plugin_id;
const _errs19 = errors;
const _errs20 = errors;
let valid3 = false;
const _errs21 = errors;
if(typeof data5 !== "string"){
const err6 = {instancePath:instancePath+"/importer_plugin_id",schemaPath:"#/properties/importer_plugin_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs21 === errors;
valid3 = valid3 || _valid2;
const _errs23 = errors;
if(data5 !== null){
const err7 = {instancePath:instancePath+"/importer_plugin_id",schemaPath:"#/properties/importer_plugin_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs23 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/importer_plugin_id",schemaPath:"#/properties/importer_plugin_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs20;
if(vErrors !== null){
if(_errs20){
vErrors.length = _errs20;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.included_source_ids !== undefined){
let data6 = data.included_source_ids;
const _errs25 = errors;
if(errors === _errs25){
if(Array.isArray(data6)){
var valid4 = true;
const len0 = data6.length;
for(let i0=0; i0<len0; i0++){
const _errs27 = errors;
if(typeof data6[i0] !== "string"){
validate53.errors = [{instancePath:instancePath+"/included_source_ids/" + i0,schemaPath:"#/properties/included_source_ids/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid4 = _errs27 === errors;
if(!valid4){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/included_source_ids",schemaPath:"#/properties/included_source_ids/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.job_id !== undefined){
const _errs29 = errors;
if(typeof data.job_id !== "string"){
validate53.errors = [{instancePath:instancePath+"/job_id",schemaPath:"#/properties/job_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.meaningful_records !== undefined){
let data9 = data.meaningful_records;
const _errs31 = errors;
if(!((typeof data9 == "number") && (!(data9 % 1) && !isNaN(data9)))){
validate53.errors = [{instancePath:instancePath+"/meaningful_records",schemaPath:"#/properties/meaningful_records/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs31 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.participants !== undefined){
let data10 = data.participants;
const _errs33 = errors;
if(errors === _errs33){
if(Array.isArray(data10)){
var valid5 = true;
const len1 = data10.length;
for(let i1=0; i1<len1; i1++){
const _errs35 = errors;
if(!(validate54(data10[i1], {instancePath:instancePath+"/participants/" + i1,parentData:data10,parentDataProperty:i1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var valid5 = _errs35 === errors;
if(!valid5){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/participants",schemaPath:"#/properties/participants/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs33 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.preview_records !== undefined){
let data12 = data.preview_records;
const _errs36 = errors;
if(errors === _errs36){
if(Array.isArray(data12)){
var valid6 = true;
const len2 = data12.length;
for(let i2=0; i2<len2; i2++){
const _errs38 = errors;
if(!(validate56(data12[i2], {instancePath:instancePath+"/preview_records/" + i2,parentData:data12,parentDataProperty:i2,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid6 = _errs38 === errors;
if(!valid6){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/preview_records",schemaPath:"#/properties/preview_records/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.projected_count !== undefined){
let data14 = data.projected_count;
const _errs39 = errors;
if(!((typeof data14 == "number") && (!(data14 % 1) && !isNaN(data14)))){
validate53.errors = [{instancePath:instancePath+"/projected_count",schemaPath:"#/properties/projected_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs39 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.quick_imported_count !== undefined){
let data15 = data.quick_imported_count;
const _errs41 = errors;
if(!((typeof data15 == "number") && (!(data15 % 1) && !isNaN(data15)))){
validate53.errors = [{instancePath:instancePath+"/quick_imported_count",schemaPath:"#/properties/quick_imported_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs41 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.quick_max_records !== undefined){
let data16 = data.quick_max_records;
const _errs43 = errors;
if(!((typeof data16 == "number") && (!(data16 % 1) && !isNaN(data16)))){
validate53.errors = [{instancePath:instancePath+"/quick_max_records",schemaPath:"#/properties/quick_max_records/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs43 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.quick_ready !== undefined){
const _errs45 = errors;
if(typeof data.quick_ready !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/quick_ready",schemaPath:"#/properties/quick_ready/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs45 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.quick_target_records !== undefined){
let data18 = data.quick_target_records;
const _errs47 = errors;
if(!((typeof data18 == "number") && (!(data18 % 1) && !isNaN(data18)))){
validate53.errors = [{instancePath:instancePath+"/quick_target_records",schemaPath:"#/properties/quick_target_records/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs47 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.self_participant_ids !== undefined){
let data19 = data.self_participant_ids;
const _errs49 = errors;
if(errors === _errs49){
if(Array.isArray(data19)){
var valid7 = true;
const len3 = data19.length;
for(let i3=0; i3<len3; i3++){
const _errs51 = errors;
if(typeof data19[i3] !== "string"){
validate53.errors = [{instancePath:instancePath+"/self_participant_ids/" + i3,schemaPath:"#/properties/self_participant_ids/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid7 = _errs51 === errors;
if(!valid7){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/self_participant_ids",schemaPath:"#/properties/self_participant_ids/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs49 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_ids !== undefined){
let data21 = data.source_ids;
const _errs53 = errors;
if(errors === _errs53){
if(Array.isArray(data21)){
var valid8 = true;
const len4 = data21.length;
for(let i4=0; i4<len4; i4++){
const _errs55 = errors;
if(typeof data21[i4] !== "string"){
validate53.errors = [{instancePath:instancePath+"/source_ids/" + i4,schemaPath:"#/properties/source_ids/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid8 = _errs55 === errors;
if(!valid8){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/source_ids",schemaPath:"#/properties/source_ids/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs53 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_type !== undefined){
const _errs57 = errors;
if(typeof data.source_type !== "string"){
validate53.errors = [{instancePath:instancePath+"/source_type",schemaPath:"#/properties/source_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs57 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sources !== undefined){
let data24 = data.sources;
const _errs59 = errors;
if(errors === _errs59){
if(Array.isArray(data24)){
var valid9 = true;
const len5 = data24.length;
for(let i5=0; i5<len5; i5++){
const _errs61 = errors;
if(!(validate58(data24[i5], {instancePath:instancePath+"/sources/" + i5,parentData:data24,parentDataProperty:i5,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate58.errors : vErrors.concat(validate58.errors);
errors = vErrors.length;
}
var valid9 = _errs61 === errors;
if(!valid9){
break;
}
}
}
else {
validate53.errors = [{instancePath:instancePath+"/sources",schemaPath:"#/properties/sources/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs59 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data26 = data.status;
const _errs62 = errors;
if(typeof data26 !== "string"){
validate53.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((data26 === "preview_ready") || (data26 === "running")) || (data26 === "ready")) || (data26 === "completed")) || (data26 === "failed")) || (data26 === "deleted"))){
validate53.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema20.properties.status.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs62 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.total_records !== undefined){
let data27 = data.total_records;
const _errs64 = errors;
if(!((typeof data27 == "number") && (!(data27 % 1) && !isNaN(data27)))){
validate53.errors = [{instancePath:instancePath+"/total_records",schemaPath:"#/properties/total_records/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs64 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.updated_at !== undefined){
const _errs66 = errors;
if(!(typeof data.updated_at == "number")){
validate53.errors = [{instancePath:instancePath+"/updated_at",schemaPath:"#/properties/updated_at/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs66 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.warning_summary !== undefined){
const _errs68 = errors;
if(!(validate60(data.warning_summary, {instancePath:instancePath+"/warning_summary",parentData:data,parentDataProperty:"warning_summary",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate60.errors : vErrors.concat(validate60.errors);
errors = vErrors.length;
}
var valid0 = _errs68 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":{"created_at":true,"detected_kind":true,"error_code":true,"imported_count":true,"importer_id":true,"importer_plugin_id":true,"included_source_ids":true,"job_id":true,"meaningful_records":true,"participants":true,"preview_records":true,"projected_count":true,"quick_imported_count":true,"quick_max_records":true,"quick_ready":true,"quick_target_records":true,"self_participant_ids":true,"source_ids":true,"source_type":true,"sources":true,"status":true,"total_records":true,"updated_at":true,"warning_summary":true},"dynamicProps":false,"dynamicItems":false};

export const validateHistoryImportAppendResponse = validate62;
const schema25 = {"properties":{"added_source_count":{"title":"Added Source Count","type":"integer"},"duplicate_source_count":{"title":"Duplicate Source Count","type":"integer"},"job":{"$ref":"#/components/schemas/HistoryImportJobResponse"}},"required":["job","added_source_count","duplicate_source_count"],"title":"HistoryImportAppendResponse","type":"object"};

function validate62(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate62.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.job === undefined) && (missing0 = "job")) || ((data.added_source_count === undefined) && (missing0 = "added_source_count"))) || ((data.duplicate_source_count === undefined) && (missing0 = "duplicate_source_count"))){
validate62.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.added_source_count !== undefined){
let data0 = data.added_source_count;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate62.errors = [{instancePath:instancePath+"/added_source_count",schemaPath:"#/properties/added_source_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.duplicate_source_count !== undefined){
let data1 = data.duplicate_source_count;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate62.errors = [{instancePath:instancePath+"/duplicate_source_count",schemaPath:"#/properties/duplicate_source_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.job !== undefined){
const _errs5 = errors;
if(!(validate53(data.job, {instancePath:instancePath+"/job",parentData:data,parentDataProperty:"job",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate53.errors : vErrors.concat(validate53.errors);
errors = vErrors.length;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate62.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate62.errors = vErrors;
return errors === 0;
}
validate62.evaluated = {"props":{"added_source_count":true,"duplicate_source_count":true,"job":true},"dynamicProps":false,"dynamicItems":false};

export const validateHistoryImporterResponse = validate64;
const schema26 = {"properties":{"accepted_extensions":{"items":{"type":"string"},"title":"Accepted Extensions","type":"array"},"description":{"title":"Description","type":"string"},"description_i18n":{"additionalProperties":{"type":"string"},"title":"Description I18N","type":"object"},"display_name":{"title":"Display Name","type":"string"},"display_name_i18n":{"additionalProperties":{"type":"string"},"title":"Display Name I18N","type":"object"},"export_help_url":{"anyOf":[{"type":"string"},{"type":"null"}],"title":"Export Help Url"},"importer_id":{"title":"Importer Id","type":"string"},"participant_identity_scope":{"enum":["source","export"],"title":"Participant Identity Scope","type":"string"},"plugin_id":{"title":"Plugin Id","type":"string"}},"required":["plugin_id","importer_id","display_name","display_name_i18n","description","description_i18n","accepted_extensions","participant_identity_scope","export_help_url"],"title":"HistoryImporterResponse","type":"object"};

function validate64(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate64.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((((data.plugin_id === undefined) && (missing0 = "plugin_id")) || ((data.importer_id === undefined) && (missing0 = "importer_id"))) || ((data.display_name === undefined) && (missing0 = "display_name"))) || ((data.display_name_i18n === undefined) && (missing0 = "display_name_i18n"))) || ((data.description === undefined) && (missing0 = "description"))) || ((data.description_i18n === undefined) && (missing0 = "description_i18n"))) || ((data.accepted_extensions === undefined) && (missing0 = "accepted_extensions"))) || ((data.participant_identity_scope === undefined) && (missing0 = "participant_identity_scope"))) || ((data.export_help_url === undefined) && (missing0 = "export_help_url"))){
validate64.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.accepted_extensions !== undefined){
let data0 = data.accepted_extensions;
const _errs1 = errors;
if(errors === _errs1){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
const _errs3 = errors;
if(typeof data0[i0] !== "string"){
validate64.errors = [{instancePath:instancePath+"/accepted_extensions/" + i0,schemaPath:"#/properties/accepted_extensions/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs3 === errors;
if(!valid1){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/accepted_extensions",schemaPath:"#/properties/accepted_extensions/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description !== undefined){
const _errs5 = errors;
if(typeof data.description !== "string"){
validate64.errors = [{instancePath:instancePath+"/description",schemaPath:"#/properties/description/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.description_i18n !== undefined){
let data3 = data.description_i18n;
const _errs7 = errors;
if(errors === _errs7){
if(data3 && typeof data3 == "object" && !Array.isArray(data3)){
for(const key0 in data3){
const _errs10 = errors;
if(typeof data3[key0] !== "string"){
validate64.errors = [{instancePath:instancePath+"/description_i18n/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/description_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs10 === errors;
if(!valid2){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/description_i18n",schemaPath:"#/properties/description_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name !== undefined){
const _errs12 = errors;
if(typeof data.display_name !== "string"){
validate64.errors = [{instancePath:instancePath+"/display_name",schemaPath:"#/properties/display_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.display_name_i18n !== undefined){
let data6 = data.display_name_i18n;
const _errs14 = errors;
if(errors === _errs14){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
for(const key1 in data6){
const _errs17 = errors;
if(typeof data6[key1] !== "string"){
validate64.errors = [{instancePath:instancePath+"/display_name_i18n/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/display_name_i18n/additionalProperties/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs17 === errors;
if(!valid3){
break;
}
}
}
else {
validate64.errors = [{instancePath:instancePath+"/display_name_i18n",schemaPath:"#/properties/display_name_i18n/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.export_help_url !== undefined){
let data8 = data.export_help_url;
const _errs19 = errors;
const _errs20 = errors;
let valid4 = false;
const _errs21 = errors;
if(typeof data8 !== "string"){
const err0 = {instancePath:instancePath+"/export_help_url",schemaPath:"#/properties/export_help_url/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs21 === errors;
valid4 = valid4 || _valid0;
const _errs23 = errors;
if(data8 !== null){
const err1 = {instancePath:instancePath+"/export_help_url",schemaPath:"#/properties/export_help_url/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs23 === errors;
valid4 = valid4 || _valid0;
if(!valid4){
const err2 = {instancePath:instancePath+"/export_help_url",schemaPath:"#/properties/export_help_url/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate64.errors = vErrors;
return false;
}
else {
errors = _errs20;
if(vErrors !== null){
if(_errs20){
vErrors.length = _errs20;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs19 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.importer_id !== undefined){
const _errs25 = errors;
if(typeof data.importer_id !== "string"){
validate64.errors = [{instancePath:instancePath+"/importer_id",schemaPath:"#/properties/importer_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.participant_identity_scope !== undefined){
let data10 = data.participant_identity_scope;
const _errs27 = errors;
if(typeof data10 !== "string"){
validate64.errors = [{instancePath:instancePath+"/participant_identity_scope",schemaPath:"#/properties/participant_identity_scope/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data10 === "source") || (data10 === "export"))){
validate64.errors = [{instancePath:instancePath+"/participant_identity_scope",schemaPath:"#/properties/participant_identity_scope/enum",keyword:"enum",params:{allowedValues: schema26.properties.participant_identity_scope.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.plugin_id !== undefined){
const _errs29 = errors;
if(typeof data.plugin_id !== "string"){
validate64.errors = [{instancePath:instancePath+"/plugin_id",schemaPath:"#/properties/plugin_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
else {
validate64.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate64.errors = vErrors;
return errors === 0;
}
validate64.evaluated = {"props":{"accepted_extensions":true,"description":true,"description_i18n":true,"display_name":true,"display_name_i18n":true,"export_help_url":true,"importer_id":true,"participant_identity_scope":true,"plugin_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateHistoryImportSourcePreviewResponse = validate65;
const schema27 = {"properties":{"detected_kind":{"enum":["document","chat","mixed"],"title":"Detected Kind","type":"string"},"records":{"items":{"$ref":"#/components/schemas/HistoryImportRecordPreviewResponse"},"title":"Records","type":"array"},"source_id":{"title":"Source Id","type":"string"},"source_name":{"title":"Source Name","type":"string"},"truncated":{"title":"Truncated","type":"boolean"}},"required":["source_id","source_name","detected_kind","records","truncated"],"title":"HistoryImportSourcePreviewResponse","type":"object"};

function validate65(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate65.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.source_id === undefined) && (missing0 = "source_id")) || ((data.source_name === undefined) && (missing0 = "source_name"))) || ((data.detected_kind === undefined) && (missing0 = "detected_kind"))) || ((data.records === undefined) && (missing0 = "records"))) || ((data.truncated === undefined) && (missing0 = "truncated"))){
validate65.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.detected_kind !== undefined){
let data0 = data.detected_kind;
const _errs1 = errors;
if(typeof data0 !== "string"){
validate65.errors = [{instancePath:instancePath+"/detected_kind",schemaPath:"#/properties/detected_kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data0 === "document") || (data0 === "chat")) || (data0 === "mixed"))){
validate65.errors = [{instancePath:instancePath+"/detected_kind",schemaPath:"#/properties/detected_kind/enum",keyword:"enum",params:{allowedValues: schema27.properties.detected_kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.records !== undefined){
let data1 = data.records;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(!(validate56(data1[i0], {instancePath:instancePath+"/records/" + i0,parentData:data1,parentDataProperty:i0,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate65.errors = [{instancePath:instancePath+"/records",schemaPath:"#/properties/records/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_id !== undefined){
const _errs6 = errors;
if(typeof data.source_id !== "string"){
validate65.errors = [{instancePath:instancePath+"/source_id",schemaPath:"#/properties/source_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_name !== undefined){
const _errs8 = errors;
if(typeof data.source_name !== "string"){
validate65.errors = [{instancePath:instancePath+"/source_name",schemaPath:"#/properties/source_name/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.truncated !== undefined){
const _errs10 = errors;
if(typeof data.truncated !== "boolean"){
validate65.errors = [{instancePath:instancePath+"/truncated",schemaPath:"#/properties/truncated/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate65.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate65.errors = vErrors;
return errors === 0;
}
validate65.evaluated = {"props":{"detected_kind":true,"records":true,"source_id":true,"source_name":true,"truncated":true},"dynamicProps":false,"dynamicItems":false};

export const validateMemoryPortabilityOperation = validate67;
const schema28 = {"additionalProperties":false,"description":"User-facing snapshot of one memory portability job.","properties":{"completed_at":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Completed At"},"created_at":{"title":"Created At","type":"string"},"error_code":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error Code"},"error_message":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error Message"},"file_size_bytes":{"anyOf":[{"minimum":0,"type":"integer"},{"type":"null"}],"default":null,"title":"File Size Bytes"},"index_rebuild_status":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Index Rebuild Status"},"inspection":{"anyOf":[{"discriminator":{"mapping":{"password_required":"#/components/schemas/PasswordRequiredMemoryRestoreInspection","ready":"#/components/schemas/ReadyMemoryRestoreInspection"},"propertyName":"state"},"oneOf":[{"$ref":"#/components/schemas/PasswordRequiredMemoryRestoreInspection"},{"$ref":"#/components/schemas/ReadyMemoryRestoreInspection"}]},{"type":"null"}],"default":null,"title":"Inspection"},"kind":{"enum":["backup","export","inspect","restore"],"title":"Kind","type":"string"},"operation_id":{"title":"Operation Id","type":"string"},"output_path":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Output Path"},"phase":{"default":"queued","title":"Phase","type":"string"},"progress_percent":{"default":0,"maximum":100,"minimum":0,"title":"Progress Percent","type":"number"},"record_counts":{"additionalProperties":{"type":"integer"},"title":"Record Counts","type":"object"},"rollback_performed":{"default":false,"title":"Rollback Performed","type":"boolean"},"safety_backup_path":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Safety Backup Path"},"status":{"default":"pending","enum":["pending","running","succeeded","failed"],"title":"Status","type":"string"}},"required":["operation_id","kind","status","phase","progress_percent","record_counts","output_path","file_size_bytes","created_at","completed_at","error_code","error_message","rollback_performed","safety_backup_path","index_rebuild_status","inspection"],"title":"MemoryPortabilityOperation","type":"object"};
const func1 = Object.prototype.hasOwnProperty;
const schema29 = {"additionalProperties":false,"description":"Secret-free result for an encrypted package awaiting a password.","properties":{"encrypted":{"const":true,"title":"Encrypted","type":"boolean"},"state":{"type":"string","enum":["password_required"],"description":"discriminator enum property added by openapi-typescript"}},"required":["state","encrypted"],"title":"PasswordRequiredMemoryRestoreInspection","type":"object"};

function validate68(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate68.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.state === undefined) && (missing0 = "state")) || ((data.encrypted === undefined) && (missing0 = "encrypted"))){
validate68.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((key0 === "encrypted") || (key0 === "state"))){
validate68.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.encrypted !== undefined){
let data0 = data.encrypted;
const _errs2 = errors;
if(typeof data0 !== "boolean"){
validate68.errors = [{instancePath:instancePath+"/encrypted",schemaPath:"#/properties/encrypted/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
if(true !== data0){
validate68.errors = [{instancePath:instancePath+"/encrypted",schemaPath:"#/properties/encrypted/const",keyword:"const",params:{allowedValue: true},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data1 = data.state;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate68.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data1 === "password_required")){
validate68.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema29.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate68.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate68.errors = vErrors;
return errors === 0;
}
validate68.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema30 = {"additionalProperties":false,"description":"Validated metadata for one private restore candidate.","properties":{"candidate_id":{"title":"Candidate Id","type":"string"},"compatibility":{"enum":["compatible","upgrade_required","unsupported"],"title":"Compatibility","type":"string"},"created_at":{"title":"Created At","type":"string"},"encrypted":{"title":"Encrypted","type":"boolean"},"expires_at":{"title":"Expires At","type":"string"},"format_version":{"minimum":1,"title":"Format Version","type":"integer"},"magi_version":{"title":"Magi Version","type":"string"},"record_counts":{"additionalProperties":{"type":"integer"},"title":"Record Counts","type":"object"},"scope":{"items":{"type":"string"},"title":"Scope","type":"array"},"source_fingerprint":{"title":"Source Fingerprint","type":"string"},"state":{"type":"string","enum":["ready"],"description":"discriminator enum property added by openapi-typescript"},"warnings":{"items":{"type":"string"},"title":"Warnings","type":"array"}},"required":["state","candidate_id","encrypted","format_version","magi_version","created_at","scope","record_counts","compatibility","warnings","expires_at","source_fingerprint"],"title":"ReadyMemoryRestoreInspection","type":"object"};

function validate70(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate70.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((data.state === undefined) && (missing0 = "state")) || ((data.candidate_id === undefined) && (missing0 = "candidate_id"))) || ((data.encrypted === undefined) && (missing0 = "encrypted"))) || ((data.format_version === undefined) && (missing0 = "format_version"))) || ((data.magi_version === undefined) && (missing0 = "magi_version"))) || ((data.created_at === undefined) && (missing0 = "created_at"))) || ((data.scope === undefined) && (missing0 = "scope"))) || ((data.record_counts === undefined) && (missing0 = "record_counts"))) || ((data.compatibility === undefined) && (missing0 = "compatibility"))) || ((data.warnings === undefined) && (missing0 = "warnings"))) || ((data.expires_at === undefined) && (missing0 = "expires_at"))) || ((data.source_fingerprint === undefined) && (missing0 = "source_fingerprint"))){
validate70.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func1.call(schema30.properties, key0))){
validate70.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.candidate_id !== undefined){
const _errs2 = errors;
if(typeof data.candidate_id !== "string"){
validate70.errors = [{instancePath:instancePath+"/candidate_id",schemaPath:"#/properties/candidate_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.compatibility !== undefined){
let data1 = data.compatibility;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate70.errors = [{instancePath:instancePath+"/compatibility",schemaPath:"#/properties/compatibility/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data1 === "compatible") || (data1 === "upgrade_required")) || (data1 === "unsupported"))){
validate70.errors = [{instancePath:instancePath+"/compatibility",schemaPath:"#/properties/compatibility/enum",keyword:"enum",params:{allowedValues: schema30.properties.compatibility.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.created_at !== undefined){
const _errs6 = errors;
if(typeof data.created_at !== "string"){
validate70.errors = [{instancePath:instancePath+"/created_at",schemaPath:"#/properties/created_at/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.encrypted !== undefined){
const _errs8 = errors;
if(typeof data.encrypted !== "boolean"){
validate70.errors = [{instancePath:instancePath+"/encrypted",schemaPath:"#/properties/encrypted/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.expires_at !== undefined){
const _errs10 = errors;
if(typeof data.expires_at !== "string"){
validate70.errors = [{instancePath:instancePath+"/expires_at",schemaPath:"#/properties/expires_at/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.format_version !== undefined){
let data5 = data.format_version;
const _errs12 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate70.errors = [{instancePath:instancePath+"/format_version",schemaPath:"#/properties/format_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs12){
if(typeof data5 == "number"){
if(data5 < 1 || isNaN(data5)){
validate70.errors = [{instancePath:instancePath+"/format_version",schemaPath:"#/properties/format_version/minimum",keyword:"minimum",params:{comparison: ">=", limit: 1},message:"must be >= 1"}];
return false;
}
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.magi_version !== undefined){
const _errs14 = errors;
if(typeof data.magi_version !== "string"){
validate70.errors = [{instancePath:instancePath+"/magi_version",schemaPath:"#/properties/magi_version/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.record_counts !== undefined){
let data7 = data.record_counts;
const _errs16 = errors;
if(errors === _errs16){
if(data7 && typeof data7 == "object" && !Array.isArray(data7)){
for(const key1 in data7){
let data8 = data7[key1];
const _errs19 = errors;
if(!((typeof data8 == "number") && (!(data8 % 1) && !isNaN(data8)))){
validate70.errors = [{instancePath:instancePath+"/record_counts/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/record_counts/additionalProperties/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid1 = _errs19 === errors;
if(!valid1){
break;
}
}
}
else {
validate70.errors = [{instancePath:instancePath+"/record_counts",schemaPath:"#/properties/record_counts/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.scope !== undefined){
let data9 = data.scope;
const _errs21 = errors;
if(errors === _errs21){
if(Array.isArray(data9)){
var valid2 = true;
const len0 = data9.length;
for(let i0=0; i0<len0; i0++){
const _errs23 = errors;
if(typeof data9[i0] !== "string"){
validate70.errors = [{instancePath:instancePath+"/scope/" + i0,schemaPath:"#/properties/scope/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs23 === errors;
if(!valid2){
break;
}
}
}
else {
validate70.errors = [{instancePath:instancePath+"/scope",schemaPath:"#/properties/scope/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs21 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.source_fingerprint !== undefined){
const _errs25 = errors;
if(typeof data.source_fingerprint !== "string"){
validate70.errors = [{instancePath:instancePath+"/source_fingerprint",schemaPath:"#/properties/source_fingerprint/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs25 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data12 = data.state;
const _errs27 = errors;
if(typeof data12 !== "string"){
validate70.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data12 === "ready")){
validate70.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/enum",keyword:"enum",params:{allowedValues: schema30.properties.state.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs27 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.warnings !== undefined){
let data13 = data.warnings;
const _errs29 = errors;
if(errors === _errs29){
if(Array.isArray(data13)){
var valid3 = true;
const len1 = data13.length;
for(let i1=0; i1<len1; i1++){
const _errs31 = errors;
if(typeof data13[i1] !== "string"){
validate70.errors = [{instancePath:instancePath+"/warnings/" + i1,schemaPath:"#/properties/warnings/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid3 = _errs31 === errors;
if(!valid3){
break;
}
}
}
else {
validate70.errors = [{instancePath:instancePath+"/warnings",schemaPath:"#/properties/warnings/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate70.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate70.errors = vErrors;
return errors === 0;
}
validate70.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate67(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate67.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((((((((((data.operation_id === undefined) && (missing0 = "operation_id")) || ((data.kind === undefined) && (missing0 = "kind"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.phase === undefined) && (missing0 = "phase"))) || ((data.progress_percent === undefined) && (missing0 = "progress_percent"))) || ((data.record_counts === undefined) && (missing0 = "record_counts"))) || ((data.output_path === undefined) && (missing0 = "output_path"))) || ((data.file_size_bytes === undefined) && (missing0 = "file_size_bytes"))) || ((data.created_at === undefined) && (missing0 = "created_at"))) || ((data.completed_at === undefined) && (missing0 = "completed_at"))) || ((data.error_code === undefined) && (missing0 = "error_code"))) || ((data.error_message === undefined) && (missing0 = "error_message"))) || ((data.rollback_performed === undefined) && (missing0 = "rollback_performed"))) || ((data.safety_backup_path === undefined) && (missing0 = "safety_backup_path"))) || ((data.index_rebuild_status === undefined) && (missing0 = "index_rebuild_status"))) || ((data.inspection === undefined) && (missing0 = "inspection"))){
validate67.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func1.call(schema28.properties, key0))){
validate67.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.completed_at !== undefined){
let data0 = data.completed_at;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/completed_at",schemaPath:"#/properties/completed_at/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs4 === errors;
valid1 = valid1 || _valid0;
const _errs6 = errors;
if(data0 !== null){
const err1 = {instancePath:instancePath+"/completed_at",schemaPath:"#/properties/completed_at/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/completed_at",schemaPath:"#/properties/completed_at/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs3;
if(vErrors !== null){
if(_errs3){
vErrors.length = _errs3;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.created_at !== undefined){
const _errs8 = errors;
if(typeof data.created_at !== "string"){
validate67.errors = [{instancePath:instancePath+"/created_at",schemaPath:"#/properties/created_at/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error_code !== undefined){
let data2 = data.error_code;
const _errs10 = errors;
const _errs11 = errors;
let valid2 = false;
const _errs12 = errors;
if(typeof data2 !== "string"){
const err3 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs12 === errors;
valid2 = valid2 || _valid1;
const _errs14 = errors;
if(data2 !== null){
const err4 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs14 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/error_code",schemaPath:"#/properties/error_code/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs11;
if(vErrors !== null){
if(_errs11){
vErrors.length = _errs11;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.error_message !== undefined){
let data3 = data.error_message;
const _errs16 = errors;
const _errs17 = errors;
let valid3 = false;
const _errs18 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/error_message",schemaPath:"#/properties/error_message/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
var _valid2 = _errs18 === errors;
valid3 = valid3 || _valid2;
const _errs20 = errors;
if(data3 !== null){
const err7 = {instancePath:instancePath+"/error_message",schemaPath:"#/properties/error_message/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs20 === errors;
valid3 = valid3 || _valid2;
if(!valid3){
const err8 = {instancePath:instancePath+"/error_message",schemaPath:"#/properties/error_message/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs17;
if(vErrors !== null){
if(_errs17){
vErrors.length = _errs17;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.file_size_bytes !== undefined){
let data4 = data.file_size_bytes;
const _errs22 = errors;
const _errs23 = errors;
let valid4 = false;
const _errs24 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
const err9 = {instancePath:instancePath+"/file_size_bytes",schemaPath:"#/properties/file_size_bytes/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
if(errors === _errs24){
if(typeof data4 == "number"){
if(data4 < 0 || isNaN(data4)){
const err10 = {instancePath:instancePath+"/file_size_bytes",schemaPath:"#/properties/file_size_bytes/anyOf/0/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
}
}
var _valid3 = _errs24 === errors;
valid4 = valid4 || _valid3;
const _errs26 = errors;
if(data4 !== null){
const err11 = {instancePath:instancePath+"/file_size_bytes",schemaPath:"#/properties/file_size_bytes/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid3 = _errs26 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err12 = {instancePath:instancePath+"/file_size_bytes",schemaPath:"#/properties/file_size_bytes/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs23;
if(vErrors !== null){
if(_errs23){
vErrors.length = _errs23;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.index_rebuild_status !== undefined){
let data5 = data.index_rebuild_status;
const _errs28 = errors;
const _errs29 = errors;
let valid5 = false;
const _errs30 = errors;
if(typeof data5 !== "string"){
const err13 = {instancePath:instancePath+"/index_rebuild_status",schemaPath:"#/properties/index_rebuild_status/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs30 === errors;
valid5 = valid5 || _valid4;
const _errs32 = errors;
if(data5 !== null){
const err14 = {instancePath:instancePath+"/index_rebuild_status",schemaPath:"#/properties/index_rebuild_status/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid4 = _errs32 === errors;
valid5 = valid5 || _valid4;
if(!valid5){
const err15 = {instancePath:instancePath+"/index_rebuild_status",schemaPath:"#/properties/index_rebuild_status/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs29;
if(vErrors !== null){
if(_errs29){
vErrors.length = _errs29;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs28 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.inspection !== undefined){
let data6 = data.inspection;
const _errs34 = errors;
const _errs35 = errors;
let valid6 = false;
const _errs36 = errors;
const _errs37 = errors;
let valid7 = false;
let passing0 = null;
const _errs38 = errors;
if(!(validate68(data6, {instancePath:instancePath+"/inspection",parentData:data,parentDataProperty:"inspection",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate68.errors : vErrors.concat(validate68.errors);
errors = vErrors.length;
}
var _valid6 = _errs38 === errors;
if(_valid6){
valid7 = true;
passing0 = 0;
var props0 = true;
}
const _errs39 = errors;
if(!(validate70(data6, {instancePath:instancePath+"/inspection",parentData:data,parentDataProperty:"inspection",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate70.errors : vErrors.concat(validate70.errors);
errors = vErrors.length;
}
var _valid6 = _errs39 === errors;
if(_valid6 && valid7){
valid7 = false;
passing0 = [passing0, 1];
}
else {
if(_valid6){
valid7 = true;
passing0 = 1;
if(props0 !== true){
props0 = true;
}
}
}
if(!valid7){
const err16 = {instancePath:instancePath+"/inspection",schemaPath:"#/properties/inspection/anyOf/0/oneOf",keyword:"oneOf",params:{passingSchemas: passing0},message:"must match exactly one schema in oneOf"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
else {
errors = _errs37;
if(vErrors !== null){
if(_errs37){
vErrors.length = _errs37;
}
else {
vErrors = null;
}
}
}
var _valid5 = _errs36 === errors;
valid6 = valid6 || _valid5;
const _errs40 = errors;
if(data6 !== null){
const err17 = {instancePath:instancePath+"/inspection",schemaPath:"#/properties/inspection/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
}
var _valid5 = _errs40 === errors;
valid6 = valid6 || _valid5;
if(!valid6){
const err18 = {instancePath:instancePath+"/inspection",schemaPath:"#/properties/inspection/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs35;
if(vErrors !== null){
if(_errs35){
vErrors.length = _errs35;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs34 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
let data7 = data.kind;
const _errs42 = errors;
if(typeof data7 !== "string"){
validate67.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((data7 === "backup") || (data7 === "export")) || (data7 === "inspect")) || (data7 === "restore"))){
validate67.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema28.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs42 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.operation_id !== undefined){
const _errs44 = errors;
if(typeof data.operation_id !== "string"){
validate67.errors = [{instancePath:instancePath+"/operation_id",schemaPath:"#/properties/operation_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs44 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.output_path !== undefined){
let data9 = data.output_path;
const _errs46 = errors;
const _errs47 = errors;
let valid8 = false;
const _errs48 = errors;
if(typeof data9 !== "string"){
const err19 = {instancePath:instancePath+"/output_path",schemaPath:"#/properties/output_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
}
var _valid7 = _errs48 === errors;
valid8 = valid8 || _valid7;
const _errs50 = errors;
if(data9 !== null){
const err20 = {instancePath:instancePath+"/output_path",schemaPath:"#/properties/output_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid7 = _errs50 === errors;
valid8 = valid8 || _valid7;
if(!valid8){
const err21 = {instancePath:instancePath+"/output_path",schemaPath:"#/properties/output_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs47;
if(vErrors !== null){
if(_errs47){
vErrors.length = _errs47;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs46 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.phase !== undefined){
const _errs52 = errors;
if(typeof data.phase !== "string"){
validate67.errors = [{instancePath:instancePath+"/phase",schemaPath:"#/properties/phase/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs52 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.progress_percent !== undefined){
let data11 = data.progress_percent;
const _errs54 = errors;
if(errors === _errs54){
if(typeof data11 == "number"){
if(data11 > 100 || isNaN(data11)){
validate67.errors = [{instancePath:instancePath+"/progress_percent",schemaPath:"#/properties/progress_percent/maximum",keyword:"maximum",params:{comparison: "<=", limit: 100},message:"must be <= 100"}];
return false;
}
else {
if(data11 < 0 || isNaN(data11)){
validate67.errors = [{instancePath:instancePath+"/progress_percent",schemaPath:"#/properties/progress_percent/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
else {
validate67.errors = [{instancePath:instancePath+"/progress_percent",schemaPath:"#/properties/progress_percent/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
}
var valid0 = _errs54 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.record_counts !== undefined){
let data12 = data.record_counts;
const _errs56 = errors;
if(errors === _errs56){
if(data12 && typeof data12 == "object" && !Array.isArray(data12)){
for(const key1 in data12){
let data13 = data12[key1];
const _errs59 = errors;
if(!((typeof data13 == "number") && (!(data13 % 1) && !isNaN(data13)))){
validate67.errors = [{instancePath:instancePath+"/record_counts/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/record_counts/additionalProperties/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid9 = _errs59 === errors;
if(!valid9){
break;
}
}
}
else {
validate67.errors = [{instancePath:instancePath+"/record_counts",schemaPath:"#/properties/record_counts/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs56 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.rollback_performed !== undefined){
const _errs61 = errors;
if(typeof data.rollback_performed !== "boolean"){
validate67.errors = [{instancePath:instancePath+"/rollback_performed",schemaPath:"#/properties/rollback_performed/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs61 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.safety_backup_path !== undefined){
let data15 = data.safety_backup_path;
const _errs63 = errors;
const _errs64 = errors;
let valid10 = false;
const _errs65 = errors;
if(typeof data15 !== "string"){
const err22 = {instancePath:instancePath+"/safety_backup_path",schemaPath:"#/properties/safety_backup_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err22];
}
else {
vErrors.push(err22);
}
errors++;
}
var _valid8 = _errs65 === errors;
valid10 = valid10 || _valid8;
const _errs67 = errors;
if(data15 !== null){
const err23 = {instancePath:instancePath+"/safety_backup_path",schemaPath:"#/properties/safety_backup_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err23];
}
else {
vErrors.push(err23);
}
errors++;
}
var _valid8 = _errs67 === errors;
valid10 = valid10 || _valid8;
if(!valid10){
const err24 = {instancePath:instancePath+"/safety_backup_path",schemaPath:"#/properties/safety_backup_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err24];
}
else {
vErrors.push(err24);
}
errors++;
validate67.errors = vErrors;
return false;
}
else {
errors = _errs64;
if(vErrors !== null){
if(_errs64){
vErrors.length = _errs64;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs63 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data16 = data.status;
const _errs69 = errors;
if(typeof data16 !== "string"){
validate67.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((data16 === "pending") || (data16 === "running")) || (data16 === "succeeded")) || (data16 === "failed"))){
validate67.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema28.properties.status.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs69 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
}
else {
validate67.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate67.errors = vErrors;
return errors === 0;
}
validate67.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateClearMemoryResponseModel = validate72;
const schema31 = {"description":"Confirmed full-memory clear with any deferred recovery warnings.","properties":{"results":{"$ref":"#/components/schemas/ClearResultsModel"},"success":{"title":"Success","type":"boolean"},"warnings":{"items":{"type":"string"},"title":"Warnings","type":"array"}},"required":["success","results","warnings"],"title":"ClearMemoryResponseModel","type":"object"};
const schema32 = {"description":"Every memory and conversation area covered by a full clear.","properties":{"chat_context":{"$ref":"#/components/schemas/ClearResultModel"},"l0":{"$ref":"#/components/schemas/ClearResultModel"},"l1":{"$ref":"#/components/schemas/ClearResultModel"},"l2":{"$ref":"#/components/schemas/ClearResultModel"},"l3":{"$ref":"#/components/schemas/ClearResultModel"},"l4":{"$ref":"#/components/schemas/ClearResultModel"}},"required":["l0","l1","l2","l3","l4","chat_context"],"title":"ClearResultsModel","type":"object"};
const schema33 = {"description":"Count returned for one cleared product area.","properties":{"cleared":{"title":"Cleared","type":"boolean"},"count":{"title":"Count","type":"integer"}},"required":["cleared","count"],"title":"ClearResultModel","type":"object"};

function validate74(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate74.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.cleared === undefined) && (missing0 = "cleared")) || ((data.count === undefined) && (missing0 = "count"))){
validate74.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.cleared !== undefined){
const _errs1 = errors;
if(typeof data.cleared !== "boolean"){
validate74.errors = [{instancePath:instancePath+"/cleared",schemaPath:"#/properties/cleared/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.count !== undefined){
let data1 = data.count;
const _errs3 = errors;
if(!((typeof data1 == "number") && (!(data1 % 1) && !isNaN(data1)))){
validate74.errors = [{instancePath:instancePath+"/count",schemaPath:"#/properties/count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate74.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate74.errors = vErrors;
return errors === 0;
}
validate74.evaluated = {"props":{"cleared":true,"count":true},"dynamicProps":false,"dynamicItems":false};


function validate73(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate73.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((data.l0 === undefined) && (missing0 = "l0")) || ((data.l1 === undefined) && (missing0 = "l1"))) || ((data.l2 === undefined) && (missing0 = "l2"))) || ((data.l3 === undefined) && (missing0 = "l3"))) || ((data.l4 === undefined) && (missing0 = "l4"))) || ((data.chat_context === undefined) && (missing0 = "chat_context"))){
validate73.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.chat_context !== undefined){
const _errs1 = errors;
if(!(validate74(data.chat_context, {instancePath:instancePath+"/chat_context",parentData:data,parentDataProperty:"chat_context",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l0 !== undefined){
const _errs2 = errors;
if(!(validate74(data.l0, {instancePath:instancePath+"/l0",parentData:data,parentDataProperty:"l0",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l1 !== undefined){
const _errs3 = errors;
if(!(validate74(data.l1, {instancePath:instancePath+"/l1",parentData:data,parentDataProperty:"l1",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l2 !== undefined){
const _errs4 = errors;
if(!(validate74(data.l2, {instancePath:instancePath+"/l2",parentData:data,parentDataProperty:"l2",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l3 !== undefined){
const _errs5 = errors;
if(!(validate74(data.l3, {instancePath:instancePath+"/l3",parentData:data,parentDataProperty:"l3",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l4 !== undefined){
const _errs6 = errors;
if(!(validate74(data.l4, {instancePath:instancePath+"/l4",parentData:data,parentDataProperty:"l4",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate74.errors : vErrors.concat(validate74.errors);
errors = vErrors.length;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
else {
validate73.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate73.errors = vErrors;
return errors === 0;
}
validate73.evaluated = {"props":{"chat_context":true,"l0":true,"l1":true,"l2":true,"l3":true,"l4":true},"dynamicProps":false,"dynamicItems":false};


function validate72(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate72.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.success === undefined) && (missing0 = "success")) || ((data.results === undefined) && (missing0 = "results"))) || ((data.warnings === undefined) && (missing0 = "warnings"))){
validate72.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.results !== undefined){
const _errs1 = errors;
if(!(validate73(data.results, {instancePath:instancePath+"/results",parentData:data,parentDataProperty:"results",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate73.errors : vErrors.concat(validate73.errors);
errors = vErrors.length;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs2 = errors;
if(typeof data.success !== "boolean"){
validate72.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.warnings !== undefined){
let data2 = data.warnings;
const _errs4 = errors;
if(errors === _errs4){
if(Array.isArray(data2)){
var valid1 = true;
const len0 = data2.length;
for(let i0=0; i0<len0; i0++){
const _errs6 = errors;
if(typeof data2[i0] !== "string"){
validate72.errors = [{instancePath:instancePath+"/warnings/" + i0,schemaPath:"#/properties/warnings/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs6 === errors;
if(!valid1){
break;
}
}
}
else {
validate72.errors = [{instancePath:instancePath+"/warnings",schemaPath:"#/properties/warnings/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate72.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate72.errors = vErrors;
return errors === 0;
}
validate72.evaluated = {"props":{"results":true,"success":true,"warnings":true},"dynamicProps":false,"dynamicItems":false};

export const validateDeleteL1EventResponse = validate82;
const schema34 = {"description":"Confirmed source-event deletion and its product scope.","properties":{"deleted":{"title":"Deleted","type":"boolean"},"deletion_scope":{"enum":["projected_memory_only","source_event"],"title":"Deletion Scope","type":"string"},"event_id":{"title":"Event Id","type":"string"}},"required":["event_id","deleted","deletion_scope"],"title":"DeleteL1EventResponse","type":"object"};

function validate82(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate82.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.event_id === undefined) && (missing0 = "event_id")) || ((data.deleted === undefined) && (missing0 = "deleted"))) || ((data.deletion_scope === undefined) && (missing0 = "deletion_scope"))){
validate82.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.deleted !== undefined){
const _errs1 = errors;
if(typeof data.deleted !== "boolean"){
validate82.errors = [{instancePath:instancePath+"/deleted",schemaPath:"#/properties/deleted/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.deletion_scope !== undefined){
let data1 = data.deletion_scope;
const _errs3 = errors;
if(typeof data1 !== "string"){
validate82.errors = [{instancePath:instancePath+"/deletion_scope",schemaPath:"#/properties/deletion_scope/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((data1 === "projected_memory_only") || (data1 === "source_event"))){
validate82.errors = [{instancePath:instancePath+"/deletion_scope",schemaPath:"#/properties/deletion_scope/enum",keyword:"enum",params:{allowedValues: schema34.properties.deletion_scope.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
const _errs5 = errors;
if(typeof data.event_id !== "string"){
validate82.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate82.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate82.errors = vErrors;
return errors === 0;
}
validate82.evaluated = {"props":{"deleted":true,"deletion_scope":true,"event_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateForgetEntityResponse = validate83;
const schema35 = {"description":"Confirmed cascade deletion counts for an entity or time range.","properties":{"l1_events_deleted":{"minimum":0,"title":"L1 Events Deleted","type":"integer"},"l2_counts":{"additionalProperties":{"type":"integer"},"title":"L2 Counts","type":"object"}},"required":["l2_counts","l1_events_deleted"],"title":"ForgetEntityResponse","type":"object"};

function validate83(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate83.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((data.l2_counts === undefined) && (missing0 = "l2_counts")) || ((data.l1_events_deleted === undefined) && (missing0 = "l1_events_deleted"))){
validate83.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.l1_events_deleted !== undefined){
let data0 = data.l1_events_deleted;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate83.errors = [{instancePath:instancePath+"/l1_events_deleted",schemaPath:"#/properties/l1_events_deleted/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs1){
if(typeof data0 == "number"){
if(data0 < 0 || isNaN(data0)){
validate83.errors = [{instancePath:instancePath+"/l1_events_deleted",schemaPath:"#/properties/l1_events_deleted/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l2_counts !== undefined){
let data1 = data.l2_counts;
const _errs3 = errors;
if(errors === _errs3){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
for(const key0 in data1){
let data2 = data1[key0];
const _errs6 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate83.errors = [{instancePath:instancePath+"/l2_counts/" + key0.replace(/~/g, "~0").replace(/\//g, "~1"),schemaPath:"#/properties/l2_counts/additionalProperties/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid1 = _errs6 === errors;
if(!valid1){
break;
}
}
}
else {
validate83.errors = [{instancePath:instancePath+"/l2_counts",schemaPath:"#/properties/l2_counts/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
}
}
}
else {
validate83.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate83.errors = vErrors;
return errors === 0;
}
validate83.evaluated = {"props":{"l1_events_deleted":true,"l2_counts":true},"dynamicProps":false,"dynamicItems":false};

export const validateForgetEpisodeResponse = validate84;
const schema36 = {"description":"Confirmed episode deletion and the affected source events.","properties":{"episode_id":{"title":"Episode Id","type":"string"},"event_ids":{"items":{"type":"string"},"title":"Event Ids","type":"array"},"l1_events_deleted":{"minimum":0,"title":"L1 Events Deleted","type":"integer"}},"required":["episode_id","event_ids","l1_events_deleted"],"title":"ForgetEpisodeResponse","type":"object"};

function validate84(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate84.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.episode_id === undefined) && (missing0 = "episode_id")) || ((data.event_ids === undefined) && (missing0 = "event_ids"))) || ((data.l1_events_deleted === undefined) && (missing0 = "l1_events_deleted"))){
validate84.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.episode_id !== undefined){
const _errs1 = errors;
if(typeof data.episode_id !== "string"){
validate84.errors = [{instancePath:instancePath+"/episode_id",schemaPath:"#/properties/episode_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_ids !== undefined){
let data1 = data.event_ids;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(typeof data1[i0] !== "string"){
validate84.errors = [{instancePath:instancePath+"/event_ids/" + i0,schemaPath:"#/properties/event_ids/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate84.errors = [{instancePath:instancePath+"/event_ids",schemaPath:"#/properties/event_ids/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.l1_events_deleted !== undefined){
let data3 = data.l1_events_deleted;
const _errs7 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate84.errors = [{instancePath:instancePath+"/l1_events_deleted",schemaPath:"#/properties/l1_events_deleted/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs7){
if(typeof data3 == "number"){
if(data3 < 0 || isNaN(data3)){
validate84.errors = [{instancePath:instancePath+"/l1_events_deleted",schemaPath:"#/properties/l1_events_deleted/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
else {
validate84.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate84.errors = vErrors;
return errors === 0;
}
validate84.evaluated = {"props":{"episode_id":true,"event_ids":true,"l1_events_deleted":true},"dynamicProps":false,"dynamicItems":false};

export const validateClearHistoryResponse = validate85;
const schema37 = {"description":"Confirmed immutable transcript snapshot removed by a history clear.","properties":{"cleanup_pending":{"default":false,"title":"Cleanup Pending","type":"boolean"},"cleared_message_ids":{"items":{"type":"string"},"title":"Cleared Message Ids","type":"array"},"cleared_turn_ids":{"items":{"type":"string"},"title":"Cleared Turn Ids","type":"array"},"message":{"title":"Message","type":"string"},"session_id":{"title":"Session Id","type":"string"},"success":{"title":"Success","type":"boolean"},"user_id":{"title":"User Id","type":"string"}},"required":["success","message","user_id","session_id","cleared_message_ids","cleared_turn_ids","cleanup_pending"],"title":"ClearHistoryResponse","type":"object"};

function validate85(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate85.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.success === undefined) && (missing0 = "success")) || ((data.message === undefined) && (missing0 = "message"))) || ((data.user_id === undefined) && (missing0 = "user_id"))) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.cleared_message_ids === undefined) && (missing0 = "cleared_message_ids"))) || ((data.cleared_turn_ids === undefined) && (missing0 = "cleared_turn_ids"))) || ((data.cleanup_pending === undefined) && (missing0 = "cleanup_pending"))){
validate85.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.cleanup_pending !== undefined){
const _errs1 = errors;
if(typeof data.cleanup_pending !== "boolean"){
validate85.errors = [{instancePath:instancePath+"/cleanup_pending",schemaPath:"#/properties/cleanup_pending/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cleared_message_ids !== undefined){
let data1 = data.cleared_message_ids;
const _errs3 = errors;
if(errors === _errs3){
if(Array.isArray(data1)){
var valid1 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
const _errs5 = errors;
if(typeof data1[i0] !== "string"){
validate85.errors = [{instancePath:instancePath+"/cleared_message_ids/" + i0,schemaPath:"#/properties/cleared_message_ids/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid1 = _errs5 === errors;
if(!valid1){
break;
}
}
}
else {
validate85.errors = [{instancePath:instancePath+"/cleared_message_ids",schemaPath:"#/properties/cleared_message_ids/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.cleared_turn_ids !== undefined){
let data3 = data.cleared_turn_ids;
const _errs7 = errors;
if(errors === _errs7){
if(Array.isArray(data3)){
var valid2 = true;
const len1 = data3.length;
for(let i1=0; i1<len1; i1++){
const _errs9 = errors;
if(typeof data3[i1] !== "string"){
validate85.errors = [{instancePath:instancePath+"/cleared_turn_ids/" + i1,schemaPath:"#/properties/cleared_turn_ids/items/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid2 = _errs9 === errors;
if(!valid2){
break;
}
}
}
else {
validate85.errors = [{instancePath:instancePath+"/cleared_turn_ids",schemaPath:"#/properties/cleared_turn_ids/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message !== undefined){
const _errs11 = errors;
if(typeof data.message !== "string"){
validate85.errors = [{instancePath:instancePath+"/message",schemaPath:"#/properties/message/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs13 = errors;
if(typeof data.session_id !== "string"){
validate85.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs15 = errors;
if(typeof data.success !== "boolean"){
validate85.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs17 = errors;
if(typeof data.user_id !== "string"){
validate85.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
}
}
else {
validate85.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate85.errors = vErrors;
return errors === 0;
}
validate85.evaluated = {"props":{"cleanup_pending":true,"cleared_message_ids":true,"cleared_turn_ids":true,"message":true,"session_id":true,"success":true,"user_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateDeleteMessageResponse = validate86;
const schema38 = {"description":"Confirmed message removal and its remaining cleanup state.","properties":{"cleanup_pending":{"default":false,"title":"Cleanup Pending","type":"boolean"},"deleted_message_id":{"title":"Deleted Message Id","type":"string"},"session_id":{"title":"Session Id","type":"string"},"success":{"title":"Success","type":"boolean"},"user_id":{"title":"User Id","type":"string"}},"required":["success","user_id","session_id","deleted_message_id","cleanup_pending"],"title":"DeleteMessageResponse","type":"object"};

function validate86(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate86.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((data.success === undefined) && (missing0 = "success")) || ((data.user_id === undefined) && (missing0 = "user_id"))) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.deleted_message_id === undefined) && (missing0 = "deleted_message_id"))) || ((data.cleanup_pending === undefined) && (missing0 = "cleanup_pending"))){
validate86.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.cleanup_pending !== undefined){
const _errs1 = errors;
if(typeof data.cleanup_pending !== "boolean"){
validate86.errors = [{instancePath:instancePath+"/cleanup_pending",schemaPath:"#/properties/cleanup_pending/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.deleted_message_id !== undefined){
const _errs3 = errors;
if(typeof data.deleted_message_id !== "string"){
validate86.errors = [{instancePath:instancePath+"/deleted_message_id",schemaPath:"#/properties/deleted_message_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs5 = errors;
if(typeof data.session_id !== "string"){
validate86.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs7 = errors;
if(typeof data.success !== "boolean"){
validate86.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs9 = errors;
if(typeof data.user_id !== "string"){
validate86.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
}
else {
validate86.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate86.errors = vErrors;
return errors === 0;
}
validate86.evaluated = {"props":{"cleanup_pending":true,"deleted_message_id":true,"session_id":true,"success":true,"user_id":true},"dynamicProps":false,"dynamicItems":false};

export const validateDeleteSessionResponse = validate87;
const schema39 = {"description":"Confirmed session removal and its remaining cleanup state.","properties":{"cleanup_pending":{"default":false,"title":"Cleanup Pending","type":"boolean"},"deleted_session_id":{"title":"Deleted Session Id","type":"string"},"success":{"title":"Success","type":"boolean"},"user_id":{"title":"User Id","type":"string"}},"required":["success","user_id","deleted_session_id","cleanup_pending"],"title":"DeleteSessionResponse","type":"object"};

function validate87(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate87.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.success === undefined) && (missing0 = "success")) || ((data.user_id === undefined) && (missing0 = "user_id"))) || ((data.deleted_session_id === undefined) && (missing0 = "deleted_session_id"))) || ((data.cleanup_pending === undefined) && (missing0 = "cleanup_pending"))){
validate87.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.cleanup_pending !== undefined){
const _errs1 = errors;
if(typeof data.cleanup_pending !== "boolean"){
validate87.errors = [{instancePath:instancePath+"/cleanup_pending",schemaPath:"#/properties/cleanup_pending/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.deleted_session_id !== undefined){
const _errs3 = errors;
if(typeof data.deleted_session_id !== "string"){
validate87.errors = [{instancePath:instancePath+"/deleted_session_id",schemaPath:"#/properties/deleted_session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.success !== undefined){
const _errs5 = errors;
if(typeof data.success !== "boolean"){
validate87.errors = [{instancePath:instancePath+"/success",schemaPath:"#/properties/success/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs7 = errors;
if(typeof data.user_id !== "string"){
validate87.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
}
}
}
}
}
else {
validate87.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate87.errors = vErrors;
return errors === 0;
}
validate87.evaluated = {"props":{"cleanup_pending":true,"deleted_session_id":true,"success":true,"user_id":true},"dynamicProps":false,"dynamicItems":false};
