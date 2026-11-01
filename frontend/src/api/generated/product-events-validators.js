// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateProductEvent = validate53;
const schema20 = {"discriminator":{"mapping":{"agent_response":"#/components/schemas/ResponseDisplayEvent","agent_response_chunk":"#/components/schemas/ResponsePreviewEvent","chat_message_hidden":"#/components/schemas/MessageHiddenEvent","chat_message_upserted":"#/components/schemas/MessageUpsertEvent","context_usage":"#/components/schemas/ContextUsageEvent","control.ask.answered":"#/components/schemas/InteractionEvent","control.ask.requested":"#/components/schemas/InteractionEvent","control.background.resumed":"#/components/schemas/InteractionEvent","control.background.suspended":"#/components/schemas/InteractionEvent","control.permission.requested":"#/components/schemas/InteractionEvent","control.permission.resolved":"#/components/schemas/InteractionEvent","control.plan.updated":"#/components/schemas/InteractionEvent","resync_required":"#/components/schemas/ResyncEvent","state.changed":"#/components/schemas/ResourceChangeEvent","turn_execution_control":"#/components/schemas/TurnControlEvent","turn_ux_plan":"#/components/schemas/TurnPresentationEvent","user_notification_added":"#/components/schemas/NotificationEvent"},"propertyName":"event_type"},"oneOf":[{"$ref":"#/components/schemas/MessageUpsertEvent"},{"$ref":"#/components/schemas/MessageHiddenEvent"},{"$ref":"#/components/schemas/TurnControlEvent"},{"$ref":"#/components/schemas/TurnPresentationEvent"},{"$ref":"#/components/schemas/ResponsePreviewEvent"},{"$ref":"#/components/schemas/ResponseDisplayEvent"},{"$ref":"#/components/schemas/ContextUsageEvent"},{"$ref":"#/components/schemas/InteractionEvent"},{"$ref":"#/components/schemas/ResourceChangeEvent"},{"$ref":"#/components/schemas/ResyncEvent"},{"$ref":"#/components/schemas/NotificationEvent"}],"title":"ProductEvent"};
const schema21 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductMessageUpsert"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["chat_message_upserted"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"MessageUpsertEvent","type":"object"};
const schema22 = {"additionalProperties":false,"properties":{"message":{"$ref":"#/components/schemas/ChatDisplayMessage"},"message_id":{"title":"Message Id","type":"string"},"session_id":{"title":"Session Id","type":"string"},"session_summary":{"anyOf":[{"$ref":"#/components/schemas/ChatSessionSummary"},{"type":"null"}],"default":null},"user_id":{"title":"User Id","type":"string"}},"required":["user_id","session_id","message_id","message"],"title":"ProductMessageUpsert","type":"object"};
const schema23 = {"description":"Typed read model for chat history and display timeline messages.","properties":{"allow_trace_collapse":{"default":false,"title":"Allow Trace Collapse","type":"boolean"},"attachments":{"anyOf":[{"items":{"additionalProperties":true,"type":"object"},"type":"array"},{"type":"null"}],"default":null,"title":"Attachments"},"content":{"title":"Content","type":"string"},"kind":{"title":"Kind","type":"string"},"label":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Label"},"message_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Id"},"message_kind":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Kind"},"payload":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Payload"},"persona_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Persona Id"},"reply_to":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Reply To"},"role":{"title":"Role","type":"string"},"run_state":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Run State"},"timestamp":{"title":"Timestamp","type":"integer"},"trace_available":{"default":false,"title":"Trace Available","type":"boolean"},"trace_display_mode":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Trace Display Mode"},"trace_summary":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null,"title":"Trace Summary"},"turn_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Turn Id"}},"required":["role","content","timestamp","kind"],"title":"ChatDisplayMessage","type":"object"};

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
if(((((data.role === undefined) && (missing0 = "role")) || ((data.content === undefined) && (missing0 = "content"))) || ((data.timestamp === undefined) && (missing0 = "timestamp"))) || ((data.kind === undefined) && (missing0 = "kind"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.allow_trace_collapse !== undefined){
const _errs1 = errors;
if(typeof data.allow_trace_collapse !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/allow_trace_collapse",schemaPath:"#/properties/allow_trace_collapse/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.attachments !== undefined){
let data1 = data.attachments;
const _errs3 = errors;
const _errs4 = errors;
let valid1 = false;
const _errs5 = errors;
if(errors === _errs5){
if(Array.isArray(data1)){
var valid2 = true;
const len0 = data1.length;
for(let i0=0; i0<len0; i0++){
let data2 = data1[i0];
const _errs7 = errors;
if(errors === _errs7){
if(data2 && typeof data2 == "object" && !Array.isArray(data2)){
}
else {
const err0 = {instancePath:instancePath+"/attachments/" + i0,schemaPath:"#/properties/attachments/anyOf/0/items/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
}
var valid2 = _errs7 === errors;
if(!valid2){
break;
}
}
}
else {
const err1 = {instancePath:instancePath+"/attachments",schemaPath:"#/properties/attachments/anyOf/0/type",keyword:"type",params:{type: "array"},message:"must be array"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
}
var _valid0 = _errs5 === errors;
valid1 = valid1 || _valid0;
const _errs10 = errors;
if(data1 !== null){
const err2 = {instancePath:instancePath+"/attachments",schemaPath:"#/properties/attachments/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err3 = {instancePath:instancePath+"/attachments",schemaPath:"#/properties/attachments/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs4;
if(vErrors !== null){
if(_errs4){
vErrors.length = _errs4;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.content !== undefined){
const _errs12 = errors;
if(typeof data.content !== "string"){
validate56.errors = [{instancePath:instancePath+"/content",schemaPath:"#/properties/content/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
const _errs14 = errors;
if(typeof data.kind !== "string"){
validate56.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
let data5 = data.label;
const _errs16 = errors;
const _errs17 = errors;
let valid3 = false;
const _errs18 = errors;
if(errors === _errs18){
if(data5 && typeof data5 == "object" && !Array.isArray(data5)){
}
else {
const err4 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
}
var _valid1 = _errs18 === errors;
valid3 = valid3 || _valid1;
const _errs21 = errors;
if(data5 !== null){
const err5 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var _valid1 = _errs21 === errors;
valid3 = valid3 || _valid1;
if(!valid3){
const err6 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
validate56.errors = vErrors;
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
if(data.message_id !== undefined){
let data6 = data.message_id;
const _errs23 = errors;
const _errs24 = errors;
let valid4 = false;
const _errs25 = errors;
if(typeof data6 !== "string"){
const err7 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs25 === errors;
valid4 = valid4 || _valid2;
const _errs27 = errors;
if(data6 !== null){
const err8 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
}
var _valid2 = _errs27 === errors;
valid4 = valid4 || _valid2;
if(!valid4){
const err9 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs24;
if(vErrors !== null){
if(_errs24){
vErrors.length = _errs24;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs23 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_kind !== undefined){
let data7 = data.message_kind;
const _errs29 = errors;
const _errs30 = errors;
let valid5 = false;
const _errs31 = errors;
if(typeof data7 !== "string"){
const err10 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs31 === errors;
valid5 = valid5 || _valid3;
const _errs33 = errors;
if(data7 !== null){
const err11 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
}
var _valid3 = _errs33 === errors;
valid5 = valid5 || _valid3;
if(!valid5){
const err12 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs30;
if(vErrors !== null){
if(_errs30){
vErrors.length = _errs30;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs29 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.payload !== undefined){
let data8 = data.payload;
const _errs35 = errors;
const _errs36 = errors;
let valid6 = false;
const _errs37 = errors;
if(errors === _errs37){
if(data8 && typeof data8 == "object" && !Array.isArray(data8)){
}
else {
const err13 = {instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
}
var _valid4 = _errs37 === errors;
valid6 = valid6 || _valid4;
const _errs40 = errors;
if(data8 !== null){
const err14 = {instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
}
var _valid4 = _errs40 === errors;
valid6 = valid6 || _valid4;
if(!valid6){
const err15 = {instancePath:instancePath+"/payload",schemaPath:"#/properties/payload/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs36;
if(vErrors !== null){
if(_errs36){
vErrors.length = _errs36;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs35 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.persona_id !== undefined){
let data9 = data.persona_id;
const _errs42 = errors;
const _errs43 = errors;
let valid7 = false;
const _errs44 = errors;
if(typeof data9 !== "string"){
const err16 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
var _valid5 = _errs44 === errors;
valid7 = valid7 || _valid5;
const _errs46 = errors;
if(data9 !== null){
const err17 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
}
var _valid5 = _errs46 === errors;
valid7 = valid7 || _valid5;
if(!valid7){
const err18 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs43;
if(vErrors !== null){
if(_errs43){
vErrors.length = _errs43;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs42 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reply_to !== undefined){
let data10 = data.reply_to;
const _errs48 = errors;
const _errs49 = errors;
let valid8 = false;
const _errs50 = errors;
if(errors === _errs50){
if(data10 && typeof data10 == "object" && !Array.isArray(data10)){
}
else {
const err19 = {instancePath:instancePath+"/reply_to",schemaPath:"#/properties/reply_to/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
}
}
var _valid6 = _errs50 === errors;
valid8 = valid8 || _valid6;
const _errs53 = errors;
if(data10 !== null){
const err20 = {instancePath:instancePath+"/reply_to",schemaPath:"#/properties/reply_to/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
}
var _valid6 = _errs53 === errors;
valid8 = valid8 || _valid6;
if(!valid8){
const err21 = {instancePath:instancePath+"/reply_to",schemaPath:"#/properties/reply_to/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err21];
}
else {
vErrors.push(err21);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs49;
if(vErrors !== null){
if(_errs49){
vErrors.length = _errs49;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs48 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.role !== undefined){
const _errs55 = errors;
if(typeof data.role !== "string"){
validate56.errors = [{instancePath:instancePath+"/role",schemaPath:"#/properties/role/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs55 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.run_state !== undefined){
let data12 = data.run_state;
const _errs57 = errors;
const _errs58 = errors;
let valid9 = false;
const _errs59 = errors;
if(errors === _errs59){
if(data12 && typeof data12 == "object" && !Array.isArray(data12)){
}
else {
const err22 = {instancePath:instancePath+"/run_state",schemaPath:"#/properties/run_state/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err22];
}
else {
vErrors.push(err22);
}
errors++;
}
}
var _valid7 = _errs59 === errors;
valid9 = valid9 || _valid7;
const _errs62 = errors;
if(data12 !== null){
const err23 = {instancePath:instancePath+"/run_state",schemaPath:"#/properties/run_state/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err23];
}
else {
vErrors.push(err23);
}
errors++;
}
var _valid7 = _errs62 === errors;
valid9 = valid9 || _valid7;
if(!valid9){
const err24 = {instancePath:instancePath+"/run_state",schemaPath:"#/properties/run_state/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err24];
}
else {
vErrors.push(err24);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs58;
if(vErrors !== null){
if(_errs58){
vErrors.length = _errs58;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs57 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp !== undefined){
let data13 = data.timestamp;
const _errs64 = errors;
if(!((typeof data13 == "number") && (!(data13 % 1) && !isNaN(data13)))){
validate56.errors = [{instancePath:instancePath+"/timestamp",schemaPath:"#/properties/timestamp/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs64 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trace_available !== undefined){
const _errs66 = errors;
if(typeof data.trace_available !== "boolean"){
validate56.errors = [{instancePath:instancePath+"/trace_available",schemaPath:"#/properties/trace_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs66 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trace_display_mode !== undefined){
let data15 = data.trace_display_mode;
const _errs68 = errors;
const _errs69 = errors;
let valid10 = false;
const _errs70 = errors;
if(typeof data15 !== "string"){
const err25 = {instancePath:instancePath+"/trace_display_mode",schemaPath:"#/properties/trace_display_mode/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err25];
}
else {
vErrors.push(err25);
}
errors++;
}
var _valid8 = _errs70 === errors;
valid10 = valid10 || _valid8;
const _errs72 = errors;
if(data15 !== null){
const err26 = {instancePath:instancePath+"/trace_display_mode",schemaPath:"#/properties/trace_display_mode/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err26];
}
else {
vErrors.push(err26);
}
errors++;
}
var _valid8 = _errs72 === errors;
valid10 = valid10 || _valid8;
if(!valid10){
const err27 = {instancePath:instancePath+"/trace_display_mode",schemaPath:"#/properties/trace_display_mode/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err27];
}
else {
vErrors.push(err27);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs69;
if(vErrors !== null){
if(_errs69){
vErrors.length = _errs69;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs68 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trace_summary !== undefined){
let data16 = data.trace_summary;
const _errs74 = errors;
const _errs75 = errors;
let valid11 = false;
const _errs76 = errors;
if(errors === _errs76){
if(data16 && typeof data16 == "object" && !Array.isArray(data16)){
}
else {
const err28 = {instancePath:instancePath+"/trace_summary",schemaPath:"#/properties/trace_summary/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err28];
}
else {
vErrors.push(err28);
}
errors++;
}
}
var _valid9 = _errs76 === errors;
valid11 = valid11 || _valid9;
const _errs79 = errors;
if(data16 !== null){
const err29 = {instancePath:instancePath+"/trace_summary",schemaPath:"#/properties/trace_summary/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err29];
}
else {
vErrors.push(err29);
}
errors++;
}
var _valid9 = _errs79 === errors;
valid11 = valid11 || _valid9;
if(!valid11){
const err30 = {instancePath:instancePath+"/trace_summary",schemaPath:"#/properties/trace_summary/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err30];
}
else {
vErrors.push(err30);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs75;
if(vErrors !== null){
if(_errs75){
vErrors.length = _errs75;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs74 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
let data17 = data.turn_id;
const _errs81 = errors;
const _errs82 = errors;
let valid12 = false;
const _errs83 = errors;
if(typeof data17 !== "string"){
const err31 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err31];
}
else {
vErrors.push(err31);
}
errors++;
}
var _valid10 = _errs83 === errors;
valid12 = valid12 || _valid10;
const _errs85 = errors;
if(data17 !== null){
const err32 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err32];
}
else {
vErrors.push(err32);
}
errors++;
}
var _valid10 = _errs85 === errors;
valid12 = valid12 || _valid10;
if(!valid12){
const err33 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err33];
}
else {
vErrors.push(err33);
}
errors++;
validate56.errors = vErrors;
return false;
}
else {
errors = _errs82;
if(vErrors !== null){
if(_errs82){
vErrors.length = _errs82;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs81 === errors;
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
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":{"allow_trace_collapse":true,"attachments":true,"content":true,"kind":true,"label":true,"message_id":true,"message_kind":true,"payload":true,"persona_id":true,"reply_to":true,"role":true,"run_state":true,"timestamp":true,"trace_available":true,"trace_display_mode":true,"trace_summary":true,"turn_id":true},"dynamicProps":false,"dynamicItems":false};

const schema24 = {"description":"Typed session summary returned by the chat read model.","properties":{"history_version":{"default":0,"title":"History Version","type":"integer"},"last_message_preview":{"title":"Last Message Preview","type":"string"},"last_timestamp":{"title":"Last Timestamp","type":"integer"},"last_user_message_preview":{"title":"Last User Message Preview","type":"string"},"message_count":{"title":"Message Count","type":"integer"},"session_id":{"title":"Session Id","type":"string"},"title":{"title":"Title","type":"string"},"title_overridden":{"title":"Title Overridden","type":"boolean"},"workspace_path":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Workspace Path"}},"required":["session_id","title","last_message_preview","last_user_message_preview","title_overridden","last_timestamp","message_count"],"title":"ChatSessionSummary","type":"object"};

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
if((((((((data.session_id === undefined) && (missing0 = "session_id")) || ((data.title === undefined) && (missing0 = "title"))) || ((data.last_message_preview === undefined) && (missing0 = "last_message_preview"))) || ((data.last_user_message_preview === undefined) && (missing0 = "last_user_message_preview"))) || ((data.title_overridden === undefined) && (missing0 = "title_overridden"))) || ((data.last_timestamp === undefined) && (missing0 = "last_timestamp"))) || ((data.message_count === undefined) && (missing0 = "message_count"))){
validate58.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
if(data.history_version !== undefined){
let data0 = data.history_version;
const _errs1 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate58.errors = [{instancePath:instancePath+"/history_version",schemaPath:"#/properties/history_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs1 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_message_preview !== undefined){
const _errs3 = errors;
if(typeof data.last_message_preview !== "string"){
validate58.errors = [{instancePath:instancePath+"/last_message_preview",schemaPath:"#/properties/last_message_preview/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_timestamp !== undefined){
let data2 = data.last_timestamp;
const _errs5 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
validate58.errors = [{instancePath:instancePath+"/last_timestamp",schemaPath:"#/properties/last_timestamp/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.last_user_message_preview !== undefined){
const _errs7 = errors;
if(typeof data.last_user_message_preview !== "string"){
validate58.errors = [{instancePath:instancePath+"/last_user_message_preview",schemaPath:"#/properties/last_user_message_preview/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_count !== undefined){
let data4 = data.message_count;
const _errs9 = errors;
if(!((typeof data4 == "number") && (!(data4 % 1) && !isNaN(data4)))){
validate58.errors = [{instancePath:instancePath+"/message_count",schemaPath:"#/properties/message_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs11 = errors;
if(typeof data.session_id !== "string"){
validate58.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title !== undefined){
const _errs13 = errors;
if(typeof data.title !== "string"){
validate58.errors = [{instancePath:instancePath+"/title",schemaPath:"#/properties/title/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.title_overridden !== undefined){
const _errs15 = errors;
if(typeof data.title_overridden !== "boolean"){
validate58.errors = [{instancePath:instancePath+"/title_overridden",schemaPath:"#/properties/title_overridden/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.workspace_path !== undefined){
let data8 = data.workspace_path;
const _errs17 = errors;
const _errs18 = errors;
let valid1 = false;
const _errs19 = errors;
if(typeof data8 !== "string"){
const err0 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs19 === errors;
valid1 = valid1 || _valid0;
const _errs21 = errors;
if(data8 !== null){
const err1 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs21 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/workspace_path",schemaPath:"#/properties/workspace_path/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate58.errors = vErrors;
return false;
}
else {
errors = _errs18;
if(vErrors !== null){
if(_errs18){
vErrors.length = _errs18;
}
else {
vErrors = null;
}
}
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
validate58.evaluated = {"props":{"history_version":true,"last_message_preview":true,"last_timestamp":true,"last_user_message_preview":true,"message_count":true,"session_id":true,"title":true,"title_overridden":true,"workspace_path":true},"dynamicProps":false,"dynamicItems":false};


function validate55(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate55.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.message_id === undefined) && (missing0 = "message_id"))) || ((data.message === undefined) && (missing0 = "message"))){
validate55.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "message") || (key0 === "message_id")) || (key0 === "session_id")) || (key0 === "session_summary")) || (key0 === "user_id"))){
validate55.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.message !== undefined){
const _errs2 = errors;
if(!(validate56(data.message, {instancePath:instancePath+"/message",parentData:data,parentDataProperty:"message",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_id !== undefined){
const _errs3 = errors;
if(typeof data.message_id !== "string"){
validate55.errors = [{instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
validate55.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_summary !== undefined){
let data3 = data.session_summary;
const _errs7 = errors;
const _errs8 = errors;
let valid1 = false;
const _errs9 = errors;
if(!(validate58(data3, {instancePath:instancePath+"/session_summary",parentData:data,parentDataProperty:"session_summary",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate58.errors : vErrors.concat(validate58.errors);
errors = vErrors.length;
}
var _valid0 = _errs9 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.history_version = true;
props0.last_message_preview = true;
props0.last_timestamp = true;
props0.last_user_message_preview = true;
props0.message_count = true;
props0.session_id = true;
props0.title = true;
props0.title_overridden = true;
props0.workspace_path = true;
}
const _errs10 = errors;
if(data3 !== null){
const err0 = {instancePath:instancePath+"/session_summary",schemaPath:"#/properties/session_summary/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/session_summary",schemaPath:"#/properties/session_summary/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate55.errors = vErrors;
return false;
}
else {
errors = _errs8;
if(vErrors !== null){
if(_errs8){
vErrors.length = _errs8;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs12 = errors;
if(typeof data.user_id !== "string"){
validate55.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs12 === errors;
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
validate55.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate55.errors = vErrors;
return errors === 0;
}
validate55.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const formats0 = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const func1 = (function(value) { let length = 0; for (const character of value) { length += 1; } return length; });

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
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate54.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate54.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate54.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate55(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate55.errors : vErrors.concat(validate55.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate54.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate54.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate54.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate54.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate54.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate54.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "chat_message_upserted")){
validate54.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema21.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate54.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate54.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate54.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate54.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate54.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema25 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductMessageHidden"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["chat_message_hidden"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"MessageHiddenEvent","type":"object"};
const schema26 = {"additionalProperties":false,"properties":{"message_id":{"title":"Message Id","type":"string"},"session_id":{"title":"Session Id","type":"string"},"session_summary":{"anyOf":[{"$ref":"#/components/schemas/ChatSessionSummary"},{"type":"null"}],"default":null},"user_id":{"title":"User Id","type":"string"}},"required":["user_id","session_id","message_id"],"title":"ProductMessageHidden","type":"object"};

function validate63(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate63.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.message_id === undefined) && (missing0 = "message_id"))){
validate63.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((key0 === "message_id") || (key0 === "session_id")) || (key0 === "session_summary")) || (key0 === "user_id"))){
validate63.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.message_id !== undefined){
const _errs2 = errors;
if(typeof data.message_id !== "string"){
validate63.errors = [{instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs4 = errors;
if(typeof data.session_id !== "string"){
validate63.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_summary !== undefined){
let data2 = data.session_summary;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(!(validate58(data2, {instancePath:instancePath+"/session_summary",parentData:data,parentDataProperty:"session_summary",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate58.errors : vErrors.concat(validate58.errors);
errors = vErrors.length;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(_valid0){
var props0 = {};
props0.history_version = true;
props0.last_message_preview = true;
props0.last_timestamp = true;
props0.last_user_message_preview = true;
props0.message_count = true;
props0.session_id = true;
props0.title = true;
props0.title_overridden = true;
props0.workspace_path = true;
}
const _errs9 = errors;
if(data2 !== null){
const err0 = {instancePath:instancePath+"/session_summary",schemaPath:"#/properties/session_summary/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs9 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err1 = {instancePath:instancePath+"/session_summary",schemaPath:"#/properties/session_summary/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
validate63.errors = vErrors;
return false;
}
else {
errors = _errs7;
if(vErrors !== null){
if(_errs7){
vErrors.length = _errs7;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs11 = errors;
if(typeof data.user_id !== "string"){
validate63.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
else {
validate63.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate63.errors = vErrors;
return errors === 0;
}
validate63.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate62.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate62.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate62.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate62.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate63(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate63.errors : vErrors.concat(validate63.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate62.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate62.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate62.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate62.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate62.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate62.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "chat_message_hidden")){
validate62.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema25.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate62.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate62.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate62.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate62.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate62.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate62.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate62.errors = vErrors;
return errors === 0;
}
validate62.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema27 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductTurnControl"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["turn_execution_control"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"TurnControlEvent","type":"object"};
const schema28 = {"additionalProperties":false,"properties":{"can_cancel":{"title":"Can Cancel","type":"boolean"},"label":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Label"},"run_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Run Id"},"session_id":{"title":"Session Id","type":"string"},"state":{"title":"State","type":"string"},"timestamp":{"title":"Timestamp","type":"number"},"turn_id":{"title":"Turn Id","type":"string"},"user_id":{"title":"User Id","type":"string"}},"required":["user_id","session_id","turn_id","state","can_cancel","timestamp"],"title":"ProductTurnControl","type":"object"};

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
if(((((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.turn_id === undefined) && (missing0 = "turn_id"))) || ((data.state === undefined) && (missing0 = "state"))) || ((data.can_cancel === undefined) && (missing0 = "can_cancel"))) || ((data.timestamp === undefined) && (missing0 = "timestamp"))){
validate68.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((((key0 === "can_cancel") || (key0 === "label")) || (key0 === "run_id")) || (key0 === "session_id")) || (key0 === "state")) || (key0 === "timestamp")) || (key0 === "turn_id")) || (key0 === "user_id"))){
validate68.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.can_cancel !== undefined){
const _errs2 = errors;
if(typeof data.can_cancel !== "boolean"){
validate68.errors = [{instancePath:instancePath+"/can_cancel",schemaPath:"#/properties/can_cancel/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.label !== undefined){
let data1 = data.label;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
const _errs8 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/label",schemaPath:"#/properties/label/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate68.errors = vErrors;
return false;
}
else {
errors = _errs5;
if(vErrors !== null){
if(_errs5){
vErrors.length = _errs5;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.run_id !== undefined){
let data2 = data.run_id;
const _errs10 = errors;
const _errs11 = errors;
let valid2 = false;
const _errs12 = errors;
if(typeof data2 !== "string"){
const err3 = {instancePath:instancePath+"/run_id",schemaPath:"#/properties/run_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err4 = {instancePath:instancePath+"/run_id",schemaPath:"#/properties/run_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err5 = {instancePath:instancePath+"/run_id",schemaPath:"#/properties/run_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate68.errors = vErrors;
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
if(data.session_id !== undefined){
const _errs16 = errors;
if(typeof data.session_id !== "string"){
validate68.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
const _errs18 = errors;
if(typeof data.state !== "string"){
validate68.errors = [{instancePath:instancePath+"/state",schemaPath:"#/properties/state/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp !== undefined){
const _errs20 = errors;
if(!(typeof data.timestamp == "number")){
validate68.errors = [{instancePath:instancePath+"/timestamp",schemaPath:"#/properties/timestamp/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
const _errs22 = errors;
if(typeof data.turn_id !== "string"){
validate68.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs24 = errors;
if(typeof data.user_id !== "string"){
validate68.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs24 === errors;
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
validate68.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate68.errors = vErrors;
return errors === 0;
}
validate68.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate67.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate67.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate67.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate67.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate68(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate68.errors : vErrors.concat(validate68.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate67.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate67.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate67.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate67.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate67.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate67.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "turn_execution_control")){
validate67.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema27.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate67.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate67.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate67.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate67.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate67.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate67.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate67.errors = vErrors;
return errors === 0;
}
validate67.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema29 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductTurnPresentation"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["turn_ux_plan"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"TurnPresentationEvent","type":"object"};
const schema30 = {"additionalProperties":false,"properties":{"message_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Id"},"message_kind":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Kind"},"session_id":{"title":"Session Id","type":"string"},"timestamp":{"title":"Timestamp","type":"number"},"turn_id":{"title":"Turn Id","type":"string"},"user_id":{"title":"User Id","type":"string"},"ux_plan":{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"title":"Ux Plan","type":"object"}},"required":["user_id","session_id","turn_id","ux_plan","timestamp"],"title":"ProductTurnPresentation","type":"object"};
const schema31 = {};

function validate73(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
validate73.errors = null;
return true;
}
validate73.evaluated = {"dynamicProps":false,"dynamicItems":false};


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
if((((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.turn_id === undefined) && (missing0 = "turn_id"))) || ((data.ux_plan === undefined) && (missing0 = "ux_plan"))) || ((data.timestamp === undefined) && (missing0 = "timestamp"))){
validate72.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "message_id") || (key0 === "message_kind")) || (key0 === "session_id")) || (key0 === "timestamp")) || (key0 === "turn_id")) || (key0 === "user_id")) || (key0 === "ux_plan"))){
validate72.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.message_id !== undefined){
let data0 = data.message_id;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate72.errors = vErrors;
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
if(data.message_kind !== undefined){
let data1 = data.message_kind;
const _errs8 = errors;
const _errs9 = errors;
let valid2 = false;
const _errs10 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs10 === errors;
valid2 = valid2 || _valid1;
const _errs12 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs12 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate72.errors = vErrors;
return false;
}
else {
errors = _errs9;
if(vErrors !== null){
if(_errs9){
vErrors.length = _errs9;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs14 = errors;
if(typeof data.session_id !== "string"){
validate72.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp !== undefined){
const _errs16 = errors;
if(!(typeof data.timestamp == "number")){
validate72.errors = [{instancePath:instancePath+"/timestamp",schemaPath:"#/properties/timestamp/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
const _errs18 = errors;
if(typeof data.turn_id !== "string"){
validate72.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs20 = errors;
if(typeof data.user_id !== "string"){
validate72.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs20 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.ux_plan !== undefined){
let data6 = data.ux_plan;
const _errs22 = errors;
if(errors === _errs22){
if(data6 && typeof data6 == "object" && !Array.isArray(data6)){
for(const key1 in data6){
const _errs25 = errors;
if(!(validate73(data6[key1], {instancePath:instancePath+"/ux_plan/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data6,parentDataProperty:key1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate73.errors : vErrors.concat(validate73.errors);
errors = vErrors.length;
}
var valid3 = _errs25 === errors;
if(!valid3){
break;
}
}
}
else {
validate72.errors = [{instancePath:instancePath+"/ux_plan",schemaPath:"#/properties/ux_plan/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid0 = _errs22 === errors;
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
else {
validate72.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate72.errors = vErrors;
return errors === 0;
}
validate72.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate71(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate71.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate71.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate71.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate71.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate71.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate72(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate72.errors : vErrors.concat(validate72.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate71.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate71.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate71.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate71.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate71.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate71.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "turn_ux_plan")){
validate71.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema29.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate71.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate71.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate71.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate71.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate71.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate71.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate71.errors = vErrors;
return errors === 0;
}
validate71.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema32 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductResponsePreview"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["agent_response_chunk"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"ResponsePreviewEvent","type":"object"};
const schema33 = {"additionalProperties":false,"properties":{"event":{"$ref":"#/components/schemas/ProductTextPreview"},"is_final":{"title":"Is Final","type":"boolean"},"persona_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Persona Id"},"seq":{"title":"Seq","type":"integer"},"session_id":{"title":"Session Id","type":"string"},"timestamp":{"title":"Timestamp","type":"number"},"turn_id":{"title":"Turn Id","type":"string"},"user_id":{"title":"User Id","type":"string"}},"required":["user_id","session_id","turn_id","event","is_final","seq","timestamp"],"title":"ProductResponsePreview","type":"object"};
const schema34 = {"additionalProperties":false,"properties":{"error_kind":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error Kind"},"error_message":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Error Message"},"kind":{"enum":["text_delta","text_flush","text_reset","status_update","error","done"],"title":"Kind","type":"string"},"step_label":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Step Label"},"text":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Text"}},"required":["kind"],"title":"ProductTextPreview","type":"object"};

function validate79(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate79.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.kind === undefined) && (missing0 = "kind")){
validate79.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((key0 === "error_kind") || (key0 === "error_message")) || (key0 === "kind")) || (key0 === "step_label")) || (key0 === "text"))){
validate79.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.error_kind !== undefined){
let data0 = data.error_kind;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/error_kind",schemaPath:"#/properties/error_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/error_kind",schemaPath:"#/properties/error_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/error_kind",schemaPath:"#/properties/error_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate79.errors = vErrors;
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
if(data.error_message !== undefined){
let data1 = data.error_message;
const _errs8 = errors;
const _errs9 = errors;
let valid2 = false;
const _errs10 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/error_message",schemaPath:"#/properties/error_message/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs10 === errors;
valid2 = valid2 || _valid1;
const _errs12 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/error_message",schemaPath:"#/properties/error_message/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs12 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/error_message",schemaPath:"#/properties/error_message/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate79.errors = vErrors;
return false;
}
else {
errors = _errs9;
if(vErrors !== null){
if(_errs9){
vErrors.length = _errs9;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
let data2 = data.kind;
const _errs14 = errors;
if(typeof data2 !== "string"){
validate79.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!((((((data2 === "text_delta") || (data2 === "text_flush")) || (data2 === "text_reset")) || (data2 === "status_update")) || (data2 === "error")) || (data2 === "done"))){
validate79.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema34.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.step_label !== undefined){
let data3 = data.step_label;
const _errs16 = errors;
const _errs17 = errors;
let valid3 = false;
const _errs18 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/step_label",schemaPath:"#/properties/step_label/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err7 = {instancePath:instancePath+"/step_label",schemaPath:"#/properties/step_label/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err8 = {instancePath:instancePath+"/step_label",schemaPath:"#/properties/step_label/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate79.errors = vErrors;
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
if(data.text !== undefined){
let data4 = data.text;
const _errs22 = errors;
const _errs23 = errors;
let valid4 = false;
const _errs24 = errors;
if(typeof data4 !== "string"){
const err9 = {instancePath:instancePath+"/text",schemaPath:"#/properties/text/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs24 === errors;
valid4 = valid4 || _valid3;
const _errs26 = errors;
if(data4 !== null){
const err10 = {instancePath:instancePath+"/text",schemaPath:"#/properties/text/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs26 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/text",schemaPath:"#/properties/text/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate79.errors = vErrors;
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
}
}
}
}
}
}
}
else {
validate79.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate79.errors = vErrors;
return errors === 0;
}
validate79.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate78(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate78.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.turn_id === undefined) && (missing0 = "turn_id"))) || ((data.event === undefined) && (missing0 = "event"))) || ((data.is_final === undefined) && (missing0 = "is_final"))) || ((data.seq === undefined) && (missing0 = "seq"))) || ((data.timestamp === undefined) && (missing0 = "timestamp"))){
validate78.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((((((key0 === "event") || (key0 === "is_final")) || (key0 === "persona_id")) || (key0 === "seq")) || (key0 === "session_id")) || (key0 === "timestamp")) || (key0 === "turn_id")) || (key0 === "user_id"))){
validate78.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.event !== undefined){
const _errs2 = errors;
if(!(validate79(data.event, {instancePath:instancePath+"/event",parentData:data,parentDataProperty:"event",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate79.errors : vErrors.concat(validate79.errors);
errors = vErrors.length;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_final !== undefined){
const _errs3 = errors;
if(typeof data.is_final !== "boolean"){
validate78.errors = [{instancePath:instancePath+"/is_final",schemaPath:"#/properties/is_final/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs3 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.persona_id !== undefined){
let data2 = data.persona_id;
const _errs5 = errors;
const _errs6 = errors;
let valid1 = false;
const _errs7 = errors;
if(typeof data2 !== "string"){
const err0 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate78.errors = vErrors;
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
if(data.seq !== undefined){
let data3 = data.seq;
const _errs11 = errors;
if(!((typeof data3 == "number") && (!(data3 % 1) && !isNaN(data3)))){
validate78.errors = [{instancePath:instancePath+"/seq",schemaPath:"#/properties/seq/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
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
validate78.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs13 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp !== undefined){
const _errs15 = errors;
if(!(typeof data.timestamp == "number")){
validate78.errors = [{instancePath:instancePath+"/timestamp",schemaPath:"#/properties/timestamp/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs15 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
const _errs17 = errors;
if(typeof data.turn_id !== "string"){
validate78.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs17 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs19 = errors;
if(typeof data.user_id !== "string"){
validate78.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
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
else {
validate78.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate78.errors = vErrors;
return errors === 0;
}
validate78.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate77(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate77.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate77.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate77.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate77.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate77.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate78(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate78.errors : vErrors.concat(validate78.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate77.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate77.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate77.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate77.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate77.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate77.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "agent_response_chunk")){
validate77.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema32.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate77.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate77.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate77.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate77.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate77.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate77.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate77.errors = vErrors;
return errors === 0;
}
validate77.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema35 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductResponseDisplay"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["agent_response"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"ResponseDisplayEvent","type":"object"};
const schema36 = {"additionalProperties":false,"properties":{"attachments":{"items":{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"type":"object"},"title":"Attachments","type":"array"},"content":{"title":"Content","type":"string"},"is_final":{"title":"Is Final","type":"boolean"},"message_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Id"},"message_kind":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Message Kind"},"message_payload":{"anyOf":[{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"type":"object"},{"type":"null"}],"default":null,"title":"Message Payload"},"persona_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Persona Id"},"reply_to_message_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Reply To Message Id"},"session_id":{"title":"Session Id","type":"string"},"timestamp":{"title":"Timestamp","type":"number"},"trace_available":{"default":false,"title":"Trace Available","type":"boolean"},"turn_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Turn Id"},"user_id":{"title":"User Id","type":"string"},"ux_plan":{"anyOf":[{"additionalProperties":{"$ref":"#/components/schemas/JsonValue"},"type":"object"},{"type":"null"}],"default":null,"title":"Ux Plan"}},"required":["user_id","session_id","content","is_final","timestamp"],"title":"ProductResponseDisplay","type":"object"};
const func11 = Object.prototype.hasOwnProperty;

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
if((((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.content === undefined) && (missing0 = "content"))) || ((data.is_final === undefined) && (missing0 = "is_final"))) || ((data.timestamp === undefined) && (missing0 = "timestamp"))){
validate84.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema36.properties, key0))){
validate84.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.attachments !== undefined){
let data0 = data.attachments;
const _errs2 = errors;
if(errors === _errs2){
if(Array.isArray(data0)){
var valid1 = true;
const len0 = data0.length;
for(let i0=0; i0<len0; i0++){
let data1 = data0[i0];
const _errs4 = errors;
if(errors === _errs4){
if(data1 && typeof data1 == "object" && !Array.isArray(data1)){
for(const key1 in data1){
const _errs7 = errors;
if(!(validate73(data1[key1], {instancePath:instancePath+"/attachments/" + i0+"/" + key1.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data1,parentDataProperty:key1,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate73.errors : vErrors.concat(validate73.errors);
errors = vErrors.length;
}
var valid2 = _errs7 === errors;
if(!valid2){
break;
}
}
}
else {
validate84.errors = [{instancePath:instancePath+"/attachments/" + i0,schemaPath:"#/properties/attachments/items/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
var valid1 = _errs4 === errors;
if(!valid1){
break;
}
}
}
else {
validate84.errors = [{instancePath:instancePath+"/attachments",schemaPath:"#/properties/attachments/type",keyword:"type",params:{type: "array"},message:"must be array"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.content !== undefined){
const _errs8 = errors;
if(typeof data.content !== "string"){
validate84.errors = [{instancePath:instancePath+"/content",schemaPath:"#/properties/content/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.is_final !== undefined){
const _errs10 = errors;
if(typeof data.is_final !== "boolean"){
validate84.errors = [{instancePath:instancePath+"/is_final",schemaPath:"#/properties/is_final/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs10 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_id !== undefined){
let data5 = data.message_id;
const _errs12 = errors;
const _errs13 = errors;
let valid3 = false;
const _errs14 = errors;
if(typeof data5 !== "string"){
const err0 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs14 === errors;
valid3 = valid3 || _valid0;
const _errs16 = errors;
if(data5 !== null){
const err1 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs16 === errors;
valid3 = valid3 || _valid0;
if(!valid3){
const err2 = {instancePath:instancePath+"/message_id",schemaPath:"#/properties/message_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate84.errors = vErrors;
return false;
}
else {
errors = _errs13;
if(vErrors !== null){
if(_errs13){
vErrors.length = _errs13;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_kind !== undefined){
let data6 = data.message_kind;
const _errs18 = errors;
const _errs19 = errors;
let valid4 = false;
const _errs20 = errors;
if(typeof data6 !== "string"){
const err3 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs20 === errors;
valid4 = valid4 || _valid1;
const _errs22 = errors;
if(data6 !== null){
const err4 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs22 === errors;
valid4 = valid4 || _valid1;
if(!valid4){
const err5 = {instancePath:instancePath+"/message_kind",schemaPath:"#/properties/message_kind/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate84.errors = vErrors;
return false;
}
else {
errors = _errs19;
if(vErrors !== null){
if(_errs19){
vErrors.length = _errs19;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs18 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.message_payload !== undefined){
let data7 = data.message_payload;
const _errs24 = errors;
const _errs25 = errors;
let valid5 = false;
const _errs26 = errors;
if(errors === _errs26){
if(data7 && typeof data7 == "object" && !Array.isArray(data7)){
for(const key2 in data7){
const _errs29 = errors;
if(!(validate73(data7[key2], {instancePath:instancePath+"/message_payload/" + key2.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data7,parentDataProperty:key2,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate73.errors : vErrors.concat(validate73.errors);
errors = vErrors.length;
}
var valid6 = _errs29 === errors;
if(!valid6){
break;
}
}
}
else {
const err6 = {instancePath:instancePath+"/message_payload",schemaPath:"#/properties/message_payload/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
}
}
var _valid2 = _errs26 === errors;
valid5 = valid5 || _valid2;
const _errs30 = errors;
if(data7 !== null){
const err7 = {instancePath:instancePath+"/message_payload",schemaPath:"#/properties/message_payload/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err7];
}
else {
vErrors.push(err7);
}
errors++;
}
var _valid2 = _errs30 === errors;
valid5 = valid5 || _valid2;
if(!valid5){
const err8 = {instancePath:instancePath+"/message_payload",schemaPath:"#/properties/message_payload/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate84.errors = vErrors;
return false;
}
else {
errors = _errs25;
if(vErrors !== null){
if(_errs25){
vErrors.length = _errs25;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.persona_id !== undefined){
let data9 = data.persona_id;
const _errs32 = errors;
const _errs33 = errors;
let valid7 = false;
const _errs34 = errors;
if(typeof data9 !== "string"){
const err9 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs34 === errors;
valid7 = valid7 || _valid3;
const _errs36 = errors;
if(data9 !== null){
const err10 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs36 === errors;
valid7 = valid7 || _valid3;
if(!valid7){
const err11 = {instancePath:instancePath+"/persona_id",schemaPath:"#/properties/persona_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate84.errors = vErrors;
return false;
}
else {
errors = _errs33;
if(vErrors !== null){
if(_errs33){
vErrors.length = _errs33;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs32 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.reply_to_message_id !== undefined){
let data10 = data.reply_to_message_id;
const _errs38 = errors;
const _errs39 = errors;
let valid8 = false;
const _errs40 = errors;
if(typeof data10 !== "string"){
const err12 = {instancePath:instancePath+"/reply_to_message_id",schemaPath:"#/properties/reply_to_message_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err12];
}
else {
vErrors.push(err12);
}
errors++;
}
var _valid4 = _errs40 === errors;
valid8 = valid8 || _valid4;
const _errs42 = errors;
if(data10 !== null){
const err13 = {instancePath:instancePath+"/reply_to_message_id",schemaPath:"#/properties/reply_to_message_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err13];
}
else {
vErrors.push(err13);
}
errors++;
}
var _valid4 = _errs42 === errors;
valid8 = valid8 || _valid4;
if(!valid8){
const err14 = {instancePath:instancePath+"/reply_to_message_id",schemaPath:"#/properties/reply_to_message_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err14];
}
else {
vErrors.push(err14);
}
errors++;
validate84.errors = vErrors;
return false;
}
else {
errors = _errs39;
if(vErrors !== null){
if(_errs39){
vErrors.length = _errs39;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs38 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs44 = errors;
if(typeof data.session_id !== "string"){
validate84.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs44 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp !== undefined){
const _errs46 = errors;
if(!(typeof data.timestamp == "number")){
validate84.errors = [{instancePath:instancePath+"/timestamp",schemaPath:"#/properties/timestamp/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs46 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.trace_available !== undefined){
const _errs48 = errors;
if(typeof data.trace_available !== "boolean"){
validate84.errors = [{instancePath:instancePath+"/trace_available",schemaPath:"#/properties/trace_available/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs48 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
let data14 = data.turn_id;
const _errs50 = errors;
const _errs51 = errors;
let valid9 = false;
const _errs52 = errors;
if(typeof data14 !== "string"){
const err15 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err15];
}
else {
vErrors.push(err15);
}
errors++;
}
var _valid5 = _errs52 === errors;
valid9 = valid9 || _valid5;
const _errs54 = errors;
if(data14 !== null){
const err16 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err16];
}
else {
vErrors.push(err16);
}
errors++;
}
var _valid5 = _errs54 === errors;
valid9 = valid9 || _valid5;
if(!valid9){
const err17 = {instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err17];
}
else {
vErrors.push(err17);
}
errors++;
validate84.errors = vErrors;
return false;
}
else {
errors = _errs51;
if(vErrors !== null){
if(_errs51){
vErrors.length = _errs51;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs50 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs56 = errors;
if(typeof data.user_id !== "string"){
validate84.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs56 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.ux_plan !== undefined){
let data16 = data.ux_plan;
const _errs58 = errors;
const _errs59 = errors;
let valid10 = false;
const _errs60 = errors;
if(errors === _errs60){
if(data16 && typeof data16 == "object" && !Array.isArray(data16)){
for(const key3 in data16){
const _errs63 = errors;
if(!(validate73(data16[key3], {instancePath:instancePath+"/ux_plan/" + key3.replace(/~/g, "~0").replace(/\//g, "~1"),parentData:data16,parentDataProperty:key3,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate73.errors : vErrors.concat(validate73.errors);
errors = vErrors.length;
}
var valid11 = _errs63 === errors;
if(!valid11){
break;
}
}
}
else {
const err18 = {instancePath:instancePath+"/ux_plan",schemaPath:"#/properties/ux_plan/anyOf/0/type",keyword:"type",params:{type: "object"},message:"must be object"};
if(vErrors === null){
vErrors = [err18];
}
else {
vErrors.push(err18);
}
errors++;
}
}
var _valid6 = _errs60 === errors;
valid10 = valid10 || _valid6;
const _errs64 = errors;
if(data16 !== null){
const err19 = {instancePath:instancePath+"/ux_plan",schemaPath:"#/properties/ux_plan/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err19];
}
else {
vErrors.push(err19);
}
errors++;
}
var _valid6 = _errs64 === errors;
valid10 = valid10 || _valid6;
if(!valid10){
const err20 = {instancePath:instancePath+"/ux_plan",schemaPath:"#/properties/ux_plan/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err20];
}
else {
vErrors.push(err20);
}
errors++;
validate84.errors = vErrors;
return false;
}
else {
errors = _errs59;
if(vErrors !== null){
if(_errs59){
vErrors.length = _errs59;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs58 === errors;
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
else {
validate84.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate84.errors = vErrors;
return errors === 0;
}
validate84.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate83.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate83.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate83.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate83.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate84(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate84.errors : vErrors.concat(validate84.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate83.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate83.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate83.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate83.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate83.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate83.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "agent_response")){
validate83.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema35.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate83.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate83.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate83.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate83.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate83.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate83.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate83.errors = vErrors;
return errors === 0;
}
validate83.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema37 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductContextUsage"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["context_usage"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"ContextUsageEvent","type":"object"};
const schema38 = {"additionalProperties":false,"properties":{"input_capacity":{"title":"Input Capacity","type":"integer"},"measurement":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Measurement"},"model_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Model Id"},"model_provider":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Model Provider"},"session_id":{"title":"Session Id","type":"string"},"threshold":{"title":"Threshold","type":"number"},"timestamp":{"title":"Timestamp","type":"number"},"turn_id":{"title":"Turn Id","type":"string"},"updated_at_ms":{"anyOf":[{"type":"integer"},{"type":"null"}],"default":null,"title":"Updated At Ms"},"used_tokens":{"title":"Used Tokens","type":"integer"},"user_id":{"title":"User Id","type":"string"},"window_size":{"title":"Window Size","type":"integer"}},"required":["user_id","session_id","turn_id","used_tokens","window_size","input_capacity","threshold","timestamp"],"title":"ProductContextUsage","type":"object"};

function validate91(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate91.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if(((((((((data.user_id === undefined) && (missing0 = "user_id")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.turn_id === undefined) && (missing0 = "turn_id"))) || ((data.used_tokens === undefined) && (missing0 = "used_tokens"))) || ((data.window_size === undefined) && (missing0 = "window_size"))) || ((data.input_capacity === undefined) && (missing0 = "input_capacity"))) || ((data.threshold === undefined) && (missing0 = "threshold"))) || ((data.timestamp === undefined) && (missing0 = "timestamp"))){
validate91.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func11.call(schema38.properties, key0))){
validate91.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.input_capacity !== undefined){
let data0 = data.input_capacity;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate91.errors = [{instancePath:instancePath+"/input_capacity",schemaPath:"#/properties/input_capacity/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.measurement !== undefined){
let data1 = data.measurement;
const _errs4 = errors;
const _errs5 = errors;
let valid1 = false;
const _errs6 = errors;
if(typeof data1 !== "string"){
const err0 = {instancePath:instancePath+"/measurement",schemaPath:"#/properties/measurement/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs6 === errors;
valid1 = valid1 || _valid0;
const _errs8 = errors;
if(data1 !== null){
const err1 = {instancePath:instancePath+"/measurement",schemaPath:"#/properties/measurement/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/measurement",schemaPath:"#/properties/measurement/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate91.errors = vErrors;
return false;
}
else {
errors = _errs5;
if(vErrors !== null){
if(_errs5){
vErrors.length = _errs5;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.model_id !== undefined){
let data2 = data.model_id;
const _errs10 = errors;
const _errs11 = errors;
let valid2 = false;
const _errs12 = errors;
if(typeof data2 !== "string"){
const err3 = {instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err4 = {instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err5 = {instancePath:instancePath+"/model_id",schemaPath:"#/properties/model_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate91.errors = vErrors;
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
if(data.model_provider !== undefined){
let data3 = data.model_provider;
const _errs16 = errors;
const _errs17 = errors;
let valid3 = false;
const _errs18 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/model_provider",schemaPath:"#/properties/model_provider/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err7 = {instancePath:instancePath+"/model_provider",schemaPath:"#/properties/model_provider/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err8 = {instancePath:instancePath+"/model_provider",schemaPath:"#/properties/model_provider/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate91.errors = vErrors;
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
if(data.session_id !== undefined){
const _errs22 = errors;
if(typeof data.session_id !== "string"){
validate91.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs22 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.threshold !== undefined){
const _errs24 = errors;
if(!(typeof data.threshold == "number")){
validate91.errors = [{instancePath:instancePath+"/threshold",schemaPath:"#/properties/threshold/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.timestamp !== undefined){
const _errs26 = errors;
if(!(typeof data.timestamp == "number")){
validate91.errors = [{instancePath:instancePath+"/timestamp",schemaPath:"#/properties/timestamp/type",keyword:"type",params:{type: "number"},message:"must be number"}];
return false;
}
var valid0 = _errs26 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
const _errs28 = errors;
if(typeof data.turn_id !== "string"){
validate91.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs28 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.updated_at_ms !== undefined){
let data8 = data.updated_at_ms;
const _errs30 = errors;
const _errs31 = errors;
let valid4 = false;
const _errs32 = errors;
if(!((typeof data8 == "number") && (!(data8 % 1) && !isNaN(data8)))){
const err9 = {instancePath:instancePath+"/updated_at_ms",schemaPath:"#/properties/updated_at_ms/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err9];
}
else {
vErrors.push(err9);
}
errors++;
}
var _valid3 = _errs32 === errors;
valid4 = valid4 || _valid3;
const _errs34 = errors;
if(data8 !== null){
const err10 = {instancePath:instancePath+"/updated_at_ms",schemaPath:"#/properties/updated_at_ms/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err10];
}
else {
vErrors.push(err10);
}
errors++;
}
var _valid3 = _errs34 === errors;
valid4 = valid4 || _valid3;
if(!valid4){
const err11 = {instancePath:instancePath+"/updated_at_ms",schemaPath:"#/properties/updated_at_ms/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err11];
}
else {
vErrors.push(err11);
}
errors++;
validate91.errors = vErrors;
return false;
}
else {
errors = _errs31;
if(vErrors !== null){
if(_errs31){
vErrors.length = _errs31;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs30 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.used_tokens !== undefined){
let data9 = data.used_tokens;
const _errs36 = errors;
if(!((typeof data9 == "number") && (!(data9 % 1) && !isNaN(data9)))){
validate91.errors = [{instancePath:instancePath+"/used_tokens",schemaPath:"#/properties/used_tokens/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs36 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
const _errs38 = errors;
if(typeof data.user_id !== "string"){
validate91.errors = [{instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs38 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.window_size !== undefined){
let data11 = data.window_size;
const _errs40 = errors;
if(!((typeof data11 == "number") && (!(data11 % 1) && !isNaN(data11)))){
validate91.errors = [{instancePath:instancePath+"/window_size",schemaPath:"#/properties/window_size/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
var valid0 = _errs40 === errors;
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
validate91.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate91.errors = vErrors;
return errors === 0;
}
validate91.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate90(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate90.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate90.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate90.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate90.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate90.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate91(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate91.errors : vErrors.concat(validate91.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate90.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate90.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate90.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate90.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate90.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate90.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "context_usage")){
validate90.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema37.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate90.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate90.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate90.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate90.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate90.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate90.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate90.errors = vErrors;
return errors === 0;
}
validate90.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema39 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductInteractionPointer"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["control.ask.answered","control.ask.requested","control.background.resumed","control.background.suspended","control.permission.requested","control.permission.resolved","control.plan.updated"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"InteractionEvent","type":"object"};
const schema40 = {"additionalProperties":false,"properties":{"request_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Request Id"},"run_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"Run Id"},"session_id":{"title":"Session Id","type":"string"},"user_id":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null,"title":"User Id"}},"required":["session_id"],"title":"ProductInteractionPointer","type":"object"};

function validate95(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate95.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.session_id === undefined) && (missing0 = "session_id")){
validate95.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((key0 === "request_id") || (key0 === "run_id")) || (key0 === "session_id")) || (key0 === "user_id"))){
validate95.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.request_id !== undefined){
let data0 = data.request_id;
const _errs2 = errors;
const _errs3 = errors;
let valid1 = false;
const _errs4 = errors;
if(typeof data0 !== "string"){
const err0 = {instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err1 = {instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err2 = {instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err2];
}
else {
vErrors.push(err2);
}
errors++;
validate95.errors = vErrors;
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
if(data.run_id !== undefined){
let data1 = data.run_id;
const _errs8 = errors;
const _errs9 = errors;
let valid2 = false;
const _errs10 = errors;
if(typeof data1 !== "string"){
const err3 = {instancePath:instancePath+"/run_id",schemaPath:"#/properties/run_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
var _valid1 = _errs10 === errors;
valid2 = valid2 || _valid1;
const _errs12 = errors;
if(data1 !== null){
const err4 = {instancePath:instancePath+"/run_id",schemaPath:"#/properties/run_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs12 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err5 = {instancePath:instancePath+"/run_id",schemaPath:"#/properties/run_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
validate95.errors = vErrors;
return false;
}
else {
errors = _errs9;
if(vErrors !== null){
if(_errs9){
vErrors.length = _errs9;
}
else {
vErrors = null;
}
}
}
var valid0 = _errs8 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs14 = errors;
if(typeof data.session_id !== "string"){
validate95.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.user_id !== undefined){
let data3 = data.user_id;
const _errs16 = errors;
const _errs17 = errors;
let valid3 = false;
const _errs18 = errors;
if(typeof data3 !== "string"){
const err6 = {instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
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
const err7 = {instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
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
const err8 = {instancePath:instancePath+"/user_id",schemaPath:"#/properties/user_id/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err8];
}
else {
vErrors.push(err8);
}
errors++;
validate95.errors = vErrors;
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
}
}
}
}
}
}
else {
validate95.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate95.errors = vErrors;
return errors === 0;
}
validate95.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate94(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate94.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate94.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate94.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate94.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate94.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate95(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate95.errors : vErrors.concat(validate95.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate94.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate94.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate94.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate94.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate94.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate94.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((((((data4 === "control.ask.answered") || (data4 === "control.ask.requested")) || (data4 === "control.background.resumed")) || (data4 === "control.background.suspended")) || (data4 === "control.permission.requested")) || (data4 === "control.permission.resolved")) || (data4 === "control.plan.updated"))){
validate94.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema39.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate94.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate94.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate94.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate94.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate94.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate94.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate94.errors = vErrors;
return errors === 0;
}
validate94.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema41 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductResourceChange"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["state.changed"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"ResourceChangeEvent","type":"object"};
const schema42 = {"additionalProperties":false,"properties":{"resource":{"title":"Resource","type":"string"}},"required":["resource"],"title":"ProductResourceChange","type":"object"};

function validate99(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate99.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.resource === undefined) && (missing0 = "resource")){
validate99.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(key0 === "resource")){
validate99.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.resource !== undefined){
if(typeof data.resource !== "string"){
validate99.errors = [{instancePath:instancePath+"/resource",schemaPath:"#/properties/resource/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
}
}
else {
validate99.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate99.errors = vErrors;
return errors === 0;
}
validate99.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate98(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate98.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate98.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate98.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate98.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate98.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate99(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate99.errors : vErrors.concat(validate99.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate98.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate98.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate98.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate98.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate98.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate98.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "state.changed")){
validate98.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema41.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate98.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate98.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate98.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate98.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate98.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate98.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate98.errors = vErrors;
return errors === 0;
}
validate98.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema43 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductResyncRequired"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["resync_required"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"ResyncEvent","type":"object"};
const schema44 = {"additionalProperties":false,"properties":{"reason":{"title":"Reason","type":"string"}},"required":["reason"],"title":"ProductResyncRequired","type":"object"};

function validate103(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate103.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.reason === undefined) && (missing0 = "reason")){
validate103.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(key0 === "reason")){
validate103.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.reason !== undefined){
if(typeof data.reason !== "string"){
validate103.errors = [{instancePath:instancePath+"/reason",schemaPath:"#/properties/reason/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
}
}
else {
validate103.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate103.errors = vErrors;
return errors === 0;
}
validate103.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate102(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate102.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate102.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate102.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate102.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate102.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate103(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate103.errors : vErrors.concat(validate103.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate102.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate102.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate102.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate102.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate102.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate102.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "resync_required")){
validate102.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema43.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate102.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate102.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate102.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate102.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate102.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate102.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate102.errors = vErrors;
return errors === 0;
}
validate102.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema45 = {"additionalProperties":false,"properties":{"contract_version":{"const":1,"title":"Contract Version","type":"integer"},"data":{"$ref":"#/components/schemas/ProductNotificationCount"},"epoch":{"format":"uuid","title":"Epoch","type":"string"},"event_id":{"maxLength":100,"minLength":1,"title":"Event Id","type":"string"},"event_type":{"type":"string","enum":["user_notification_added"],"description":"discriminator enum property added by openapi-typescript"},"sequence":{"maximum":9007199254740991,"minimum":0,"title":"Sequence","type":"integer"},"server_id":{"format":"uuid","title":"Server Id","type":"string"}},"required":["contract_version","server_id","epoch","sequence","event_id","event_type","data"],"title":"NotificationEvent","type":"object"};
const schema46 = {"additionalProperties":false,"properties":{"unread_count":{"minimum":0,"title":"Unread Count","type":"integer"}},"required":["unread_count"],"title":"ProductNotificationCount","type":"object"};

function validate107(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate107.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((data.unread_count === undefined) && (missing0 = "unread_count")){
validate107.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(key0 === "unread_count")){
validate107.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.unread_count !== undefined){
let data0 = data.unread_count;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate107.errors = [{instancePath:instancePath+"/unread_count",schemaPath:"#/properties/unread_count/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs2){
if(typeof data0 == "number"){
if(data0 < 0 || isNaN(data0)){
validate107.errors = [{instancePath:instancePath+"/unread_count",schemaPath:"#/properties/unread_count/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
}
}
}
else {
validate107.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate107.errors = vErrors;
return errors === 0;
}
validate107.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


function validate106(data, {instancePath="", parentData, parentDataProperty, rootData=data, dynamicAnchors={}}={}){
let vErrors = null;
let errors = 0;
const evaluated0 = validate106.evaluated;
if(evaluated0.dynamicProps){
evaluated0.props = undefined;
}
if(evaluated0.dynamicItems){
evaluated0.items = undefined;
}
if(errors === 0){
if(data && typeof data == "object" && !Array.isArray(data)){
let missing0;
if((((((((data.contract_version === undefined) && (missing0 = "contract_version")) || ((data.server_id === undefined) && (missing0 = "server_id"))) || ((data.epoch === undefined) && (missing0 = "epoch"))) || ((data.sequence === undefined) && (missing0 = "sequence"))) || ((data.event_id === undefined) && (missing0 = "event_id"))) || ((data.event_type === undefined) && (missing0 = "event_type"))) || ((data.data === undefined) && (missing0 = "data"))){
validate106.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((((((key0 === "contract_version") || (key0 === "data")) || (key0 === "epoch")) || (key0 === "event_id")) || (key0 === "event_type")) || (key0 === "sequence")) || (key0 === "server_id"))){
validate106.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.contract_version !== undefined){
let data0 = data.contract_version;
const _errs2 = errors;
if(!((typeof data0 == "number") && (!(data0 % 1) && !isNaN(data0)))){
validate106.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(1 !== data0){
validate106.errors = [{instancePath:instancePath+"/contract_version",schemaPath:"#/properties/contract_version/const",keyword:"const",params:{allowedValue: 1},message:"must be equal to constant"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.data !== undefined){
const _errs4 = errors;
if(!(validate107(data.data, {instancePath:instancePath+"/data",parentData:data,parentDataProperty:"data",rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate107.errors : vErrors.concat(validate107.errors);
errors = vErrors.length;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.epoch !== undefined){
let data2 = data.epoch;
const _errs5 = errors;
if(errors === _errs5){
if(errors === _errs5){
if(typeof data2 === "string"){
if(!(formats0.test(data2))){
validate106.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate106.errors = [{instancePath:instancePath+"/epoch",schemaPath:"#/properties/epoch/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs5 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_id !== undefined){
let data3 = data.event_id;
const _errs7 = errors;
if(errors === _errs7){
if(typeof data3 === "string"){
if(func1(data3) > 100){
validate106.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/maxLength",keyword:"maxLength",params:{limit: 100},message:"must NOT have more than 100 characters"}];
return false;
}
else {
if(func1(data3) < 1){
validate106.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate106.errors = [{instancePath:instancePath+"/event_id",schemaPath:"#/properties/event_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs7 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.event_type !== undefined){
let data4 = data.event_type;
const _errs9 = errors;
if(typeof data4 !== "string"){
validate106.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data4 === "user_notification_added")){
validate106.errors = [{instancePath:instancePath+"/event_type",schemaPath:"#/properties/event_type/enum",keyword:"enum",params:{allowedValues: schema45.properties.event_type.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs9 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.sequence !== undefined){
let data5 = data.sequence;
const _errs11 = errors;
if(!((typeof data5 == "number") && (!(data5 % 1) && !isNaN(data5)))){
validate106.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/type",keyword:"type",params:{type: "integer"},message:"must be integer"}];
return false;
}
if(errors === _errs11){
if(typeof data5 == "number"){
if(data5 > 9007199254740991 || isNaN(data5)){
validate106.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/maximum",keyword:"maximum",params:{comparison: "<=", limit: 9007199254740991},message:"must be <= 9007199254740991"}];
return false;
}
else {
if(data5 < 0 || isNaN(data5)){
validate106.errors = [{instancePath:instancePath+"/sequence",schemaPath:"#/properties/sequence/minimum",keyword:"minimum",params:{comparison: ">=", limit: 0},message:"must be >= 0"}];
return false;
}
}
}
}
var valid0 = _errs11 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.server_id !== undefined){
let data6 = data.server_id;
const _errs13 = errors;
if(errors === _errs13){
if(errors === _errs13){
if(typeof data6 === "string"){
if(!(formats0.test(data6))){
validate106.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/format",keyword:"format",params:{format: "uuid"},message:"must match format \""+"uuid"+"\""}];
return false;
}
}
else {
validate106.errors = [{instancePath:instancePath+"/server_id",schemaPath:"#/properties/server_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
}
var valid0 = _errs13 === errors;
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
else {
validate106.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate106.errors = vErrors;
return errors === 0;
}
validate106.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
const _errs0 = errors;
let valid0 = false;
let passing0 = null;
const _errs1 = errors;
if(!(validate54(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate54.errors : vErrors.concat(validate54.errors);
errors = vErrors.length;
}
var _valid0 = _errs1 === errors;
if(_valid0){
valid0 = true;
passing0 = 0;
var props0 = true;
}
const _errs2 = errors;
if(!(validate62(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate62.errors : vErrors.concat(validate62.errors);
errors = vErrors.length;
}
var _valid0 = _errs2 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 1];
}
else {
if(_valid0){
valid0 = true;
passing0 = 1;
if(props0 !== true){
props0 = true;
}
}
const _errs3 = errors;
if(!(validate67(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate67.errors : vErrors.concat(validate67.errors);
errors = vErrors.length;
}
var _valid0 = _errs3 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 2];
}
else {
if(_valid0){
valid0 = true;
passing0 = 2;
if(props0 !== true){
props0 = true;
}
}
const _errs4 = errors;
if(!(validate71(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate71.errors : vErrors.concat(validate71.errors);
errors = vErrors.length;
}
var _valid0 = _errs4 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 3];
}
else {
if(_valid0){
valid0 = true;
passing0 = 3;
if(props0 !== true){
props0 = true;
}
}
const _errs5 = errors;
if(!(validate77(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate77.errors : vErrors.concat(validate77.errors);
errors = vErrors.length;
}
var _valid0 = _errs5 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 4];
}
else {
if(_valid0){
valid0 = true;
passing0 = 4;
if(props0 !== true){
props0 = true;
}
}
const _errs6 = errors;
if(!(validate83(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate83.errors : vErrors.concat(validate83.errors);
errors = vErrors.length;
}
var _valid0 = _errs6 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 5];
}
else {
if(_valid0){
valid0 = true;
passing0 = 5;
if(props0 !== true){
props0 = true;
}
}
const _errs7 = errors;
if(!(validate90(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate90.errors : vErrors.concat(validate90.errors);
errors = vErrors.length;
}
var _valid0 = _errs7 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 6];
}
else {
if(_valid0){
valid0 = true;
passing0 = 6;
if(props0 !== true){
props0 = true;
}
}
const _errs8 = errors;
if(!(validate94(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate94.errors : vErrors.concat(validate94.errors);
errors = vErrors.length;
}
var _valid0 = _errs8 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 7];
}
else {
if(_valid0){
valid0 = true;
passing0 = 7;
if(props0 !== true){
props0 = true;
}
}
const _errs9 = errors;
if(!(validate98(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate98.errors : vErrors.concat(validate98.errors);
errors = vErrors.length;
}
var _valid0 = _errs9 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 8];
}
else {
if(_valid0){
valid0 = true;
passing0 = 8;
if(props0 !== true){
props0 = true;
}
}
const _errs10 = errors;
if(!(validate102(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate102.errors : vErrors.concat(validate102.errors);
errors = vErrors.length;
}
var _valid0 = _errs10 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 9];
}
else {
if(_valid0){
valid0 = true;
passing0 = 9;
if(props0 !== true){
props0 = true;
}
}
const _errs11 = errors;
if(!(validate106(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate106.errors : vErrors.concat(validate106.errors);
errors = vErrors.length;
}
var _valid0 = _errs11 === errors;
if(_valid0 && valid0){
valid0 = false;
passing0 = [passing0, 10];
}
else {
if(_valid0){
valid0 = true;
passing0 = 10;
if(props0 !== true){
props0 = true;
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
if(!valid0){
const err0 = {instancePath,schemaPath:"#/oneOf",keyword:"oneOf",params:{passingSchemas: passing0},message:"must match exactly one schema in oneOf"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
validate53.errors = vErrors;
return false;
}
else {
errors = _errs0;
if(vErrors !== null){
if(_errs0){
vErrors.length = _errs0;
}
else {
vErrors = null;
}
}
}
validate53.errors = vErrors;
evaluated0.props = props0;
return errors === 0;
}
validate53.evaluated = {"dynamicProps":true,"dynamicItems":false};
