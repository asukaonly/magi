// Generated from production response schemas. Run npm run contracts:generate.
"use strict";
export const validateTurnSnapshot = validate53;
const schema20 = {"additionalProperties":false,"properties":{"acceptance":{"enum":["accepted","absent","retired"],"title":"Acceptance","type":"string"},"can_resubmit":{"title":"Can Resubmit","type":"boolean"},"presentation_ends_at_ms":{"anyOf":[{"type":"integer"},{"type":"null"}],"title":"Presentation Ends At Ms"},"response_complete":{"title":"Response Complete","type":"boolean"},"revision":{"title":"Revision","type":"string"},"session_id":{"title":"Session Id","type":"string"},"state":{"anyOf":[{"enum":["queued","running","cancelling","detaching","completed","failed","cancelled","blocked","interrupted","merged","discarded","superseded"],"type":"string"},{"type":"null"}],"title":"State"},"terminal":{"title":"Terminal","type":"boolean"},"turn_id":{"title":"Turn Id","type":"string"}},"required":["session_id","turn_id","acceptance","state","terminal","response_complete","presentation_ends_at_ms","can_resubmit","revision"],"title":"TurnSnapshot","type":"object"};
const func1 = Object.prototype.hasOwnProperty;

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
if((((((((((data.session_id === undefined) && (missing0 = "session_id")) || ((data.turn_id === undefined) && (missing0 = "turn_id"))) || ((data.acceptance === undefined) && (missing0 = "acceptance"))) || ((data.state === undefined) && (missing0 = "state"))) || ((data.terminal === undefined) && (missing0 = "terminal"))) || ((data.response_complete === undefined) && (missing0 = "response_complete"))) || ((data.presentation_ends_at_ms === undefined) && (missing0 = "presentation_ends_at_ms"))) || ((data.can_resubmit === undefined) && (missing0 = "can_resubmit"))) || ((data.revision === undefined) && (missing0 = "revision"))){
validate53.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(func1.call(schema20.properties, key0))){
validate53.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.acceptance !== undefined){
let data0 = data.acceptance;
const _errs2 = errors;
if(typeof data0 !== "string"){
validate53.errors = [{instancePath:instancePath+"/acceptance",schemaPath:"#/properties/acceptance/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data0 === "accepted") || (data0 === "absent")) || (data0 === "retired"))){
validate53.errors = [{instancePath:instancePath+"/acceptance",schemaPath:"#/properties/acceptance/enum",keyword:"enum",params:{allowedValues: schema20.properties.acceptance.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.can_resubmit !== undefined){
const _errs4 = errors;
if(typeof data.can_resubmit !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/can_resubmit",schemaPath:"#/properties/can_resubmit/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.presentation_ends_at_ms !== undefined){
let data2 = data.presentation_ends_at_ms;
const _errs6 = errors;
const _errs7 = errors;
let valid1 = false;
const _errs8 = errors;
if(!((typeof data2 == "number") && (!(data2 % 1) && !isNaN(data2)))){
const err0 = {instancePath:instancePath+"/presentation_ends_at_ms",schemaPath:"#/properties/presentation_ends_at_ms/anyOf/0/type",keyword:"type",params:{type: "integer"},message:"must be integer"};
if(vErrors === null){
vErrors = [err0];
}
else {
vErrors.push(err0);
}
errors++;
}
var _valid0 = _errs8 === errors;
valid1 = valid1 || _valid0;
const _errs10 = errors;
if(data2 !== null){
const err1 = {instancePath:instancePath+"/presentation_ends_at_ms",schemaPath:"#/properties/presentation_ends_at_ms/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err1];
}
else {
vErrors.push(err1);
}
errors++;
}
var _valid0 = _errs10 === errors;
valid1 = valid1 || _valid0;
if(!valid1){
const err2 = {instancePath:instancePath+"/presentation_ends_at_ms",schemaPath:"#/properties/presentation_ends_at_ms/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
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
if(data.response_complete !== undefined){
const _errs12 = errors;
if(typeof data.response_complete !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/response_complete",schemaPath:"#/properties/response_complete/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs12 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.revision !== undefined){
const _errs14 = errors;
if(typeof data.revision !== "string"){
validate53.errors = [{instancePath:instancePath+"/revision",schemaPath:"#/properties/revision/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs14 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs16 = errors;
if(typeof data.session_id !== "string"){
validate53.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs16 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.state !== undefined){
let data6 = data.state;
const _errs18 = errors;
const _errs19 = errors;
let valid2 = false;
const _errs20 = errors;
if(typeof data6 !== "string"){
const err3 = {instancePath:instancePath+"/state",schemaPath:"#/properties/state/anyOf/0/type",keyword:"type",params:{type: "string"},message:"must be string"};
if(vErrors === null){
vErrors = [err3];
}
else {
vErrors.push(err3);
}
errors++;
}
if(!((((((((((((data6 === "queued") || (data6 === "running")) || (data6 === "cancelling")) || (data6 === "detaching")) || (data6 === "completed")) || (data6 === "failed")) || (data6 === "cancelled")) || (data6 === "blocked")) || (data6 === "interrupted")) || (data6 === "merged")) || (data6 === "discarded")) || (data6 === "superseded"))){
const err4 = {instancePath:instancePath+"/state",schemaPath:"#/properties/state/anyOf/0/enum",keyword:"enum",params:{allowedValues: schema20.properties.state.anyOf[0].enum},message:"must be equal to one of the allowed values"};
if(vErrors === null){
vErrors = [err4];
}
else {
vErrors.push(err4);
}
errors++;
}
var _valid1 = _errs20 === errors;
valid2 = valid2 || _valid1;
const _errs22 = errors;
if(data6 !== null){
const err5 = {instancePath:instancePath+"/state",schemaPath:"#/properties/state/anyOf/1/type",keyword:"type",params:{type: "null"},message:"must be null"};
if(vErrors === null){
vErrors = [err5];
}
else {
vErrors.push(err5);
}
errors++;
}
var _valid1 = _errs22 === errors;
valid2 = valid2 || _valid1;
if(!valid2){
const err6 = {instancePath:instancePath+"/state",schemaPath:"#/properties/state/anyOf",keyword:"anyOf",params:{},message:"must match a schema in anyOf"};
if(vErrors === null){
vErrors = [err6];
}
else {
vErrors.push(err6);
}
errors++;
validate53.errors = vErrors;
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
if(data.terminal !== undefined){
const _errs24 = errors;
if(typeof data.terminal !== "boolean"){
validate53.errors = [{instancePath:instancePath+"/terminal",schemaPath:"#/properties/terminal/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs24 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
const _errs26 = errors;
if(typeof data.turn_id !== "string"){
validate53.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs26 === errors;
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
validate53.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate53.errors = vErrors;
return errors === 0;
}
validate53.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateSendConfirmation = validate54;
const schema21 = {"additionalProperties":false,"properties":{"identity":{"title":"Identity","type":"string"},"safe_to_retry":{"title":"Safe To Retry","type":"boolean"},"session_id":{"title":"Session Id","type":"string"},"status":{"enum":["confirmed","absent","concluded"],"title":"Status","type":"string"}},"required":["session_id","identity","status","safe_to_retry"],"title":"SendConfirmation","type":"object"};

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
if(((((data.session_id === undefined) && (missing0 = "session_id")) || ((data.identity === undefined) && (missing0 = "identity"))) || ((data.status === undefined) && (missing0 = "status"))) || ((data.safe_to_retry === undefined) && (missing0 = "safe_to_retry"))){
validate54.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((key0 === "identity") || (key0 === "safe_to_retry")) || (key0 === "session_id")) || (key0 === "status"))){
validate54.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.identity !== undefined){
const _errs2 = errors;
if(typeof data.identity !== "string"){
validate54.errors = [{instancePath:instancePath+"/identity",schemaPath:"#/properties/identity/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.safe_to_retry !== undefined){
const _errs4 = errors;
if(typeof data.safe_to_retry !== "boolean"){
validate54.errors = [{instancePath:instancePath+"/safe_to_retry",schemaPath:"#/properties/safe_to_retry/type",keyword:"type",params:{type: "boolean"},message:"must be boolean"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
const _errs6 = errors;
if(typeof data.session_id !== "string"){
validate54.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.status !== undefined){
let data3 = data.status;
const _errs8 = errors;
if(typeof data3 !== "string"){
validate54.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(((data3 === "confirmed") || (data3 === "absent")) || (data3 === "concluded"))){
validate54.errors = [{instancePath:instancePath+"/status",schemaPath:"#/properties/status/enum",keyword:"enum",params:{allowedValues: schema21.properties.status.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs8 === errors;
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
validate54.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate54.errors = vErrors;
return errors === 0;
}
validate54.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

export const validateSendConfirmationRequest = validate55;
const schema22 = {"discriminator":{"mapping":{"ask_response":"#/components/schemas/AnswerConfirmationRequest","turn":"#/components/schemas/TurnConfirmationRequest"},"propertyName":"kind"},"oneOf":[{"$ref":"#/components/schemas/TurnConfirmationRequest"},{"$ref":"#/components/schemas/AnswerConfirmationRequest"}],"title":"SendConfirmationRequest"};
const schema23 = {"additionalProperties":false,"properties":{"kind":{"type":"string","enum":["turn"],"description":"discriminator enum property added by openapi-typescript"},"session_id":{"maxLength":128,"minLength":1,"title":"Session Id","type":"string"},"turn_id":{"maxLength":128,"minLength":1,"title":"Turn Id","type":"string"}},"required":["kind","session_id","turn_id"],"title":"TurnConfirmationRequest","type":"object"};
const func2 = (function(value) { let length = 0; for (const character of value) { length += 1; } return length; });

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
if((((data.kind === undefined) && (missing0 = "kind")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.turn_id === undefined) && (missing0 = "turn_id"))){
validate56.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!(((key0 === "kind") || (key0 === "session_id")) || (key0 === "turn_id"))){
validate56.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.kind !== undefined){
let data0 = data.kind;
const _errs2 = errors;
if(typeof data0 !== "string"){
validate56.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data0 === "turn")){
validate56.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema23.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
let data1 = data.session_id;
const _errs4 = errors;
if(errors === _errs4){
if(typeof data1 === "string"){
if(func2(data1) > 128){
validate56.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func2(data1) < 1){
validate56.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate56.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.turn_id !== undefined){
let data2 = data.turn_id;
const _errs6 = errors;
if(errors === _errs6){
if(typeof data2 === "string"){
if(func2(data2) > 128){
validate56.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func2(data2) < 1){
validate56.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate56.errors = [{instancePath:instancePath+"/turn_id",schemaPath:"#/properties/turn_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
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
else {
validate56.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate56.errors = vErrors;
return errors === 0;
}
validate56.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};

const schema24 = {"additionalProperties":false,"properties":{"answer":{"maxLength":100000,"minLength":1,"title":"Answer","type":"string"},"kind":{"type":"string","enum":["ask_response"],"description":"discriminator enum property added by openapi-typescript"},"request_id":{"maxLength":128,"minLength":1,"title":"Request Id","type":"string"},"session_id":{"maxLength":128,"minLength":1,"title":"Session Id","type":"string"}},"required":["kind","session_id","request_id","answer"],"title":"AnswerConfirmationRequest","type":"object"};

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
if(((((data.kind === undefined) && (missing0 = "kind")) || ((data.session_id === undefined) && (missing0 = "session_id"))) || ((data.request_id === undefined) && (missing0 = "request_id"))) || ((data.answer === undefined) && (missing0 = "answer"))){
validate58.errors = [{instancePath,schemaPath:"#/required",keyword:"required",params:{missingProperty: missing0},message:"must have required property '"+missing0+"'"}];
return false;
}
else {
const _errs1 = errors;
for(const key0 in data){
if(!((((key0 === "answer") || (key0 === "kind")) || (key0 === "request_id")) || (key0 === "session_id"))){
validate58.errors = [{instancePath,schemaPath:"#/additionalProperties",keyword:"additionalProperties",params:{additionalProperty: key0},message:"must NOT have additional properties"}];
return false;
break;
}
}
if(_errs1 === errors){
if(data.answer !== undefined){
let data0 = data.answer;
const _errs2 = errors;
if(errors === _errs2){
if(typeof data0 === "string"){
if(func2(data0) > 100000){
validate58.errors = [{instancePath:instancePath+"/answer",schemaPath:"#/properties/answer/maxLength",keyword:"maxLength",params:{limit: 100000},message:"must NOT have more than 100000 characters"}];
return false;
}
else {
if(func2(data0) < 1){
validate58.errors = [{instancePath:instancePath+"/answer",schemaPath:"#/properties/answer/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate58.errors = [{instancePath:instancePath+"/answer",schemaPath:"#/properties/answer/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs2 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.kind !== undefined){
let data1 = data.kind;
const _errs4 = errors;
if(typeof data1 !== "string"){
validate58.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
if(!(data1 === "ask_response")){
validate58.errors = [{instancePath:instancePath+"/kind",schemaPath:"#/properties/kind/enum",keyword:"enum",params:{allowedValues: schema24.properties.kind.enum},message:"must be equal to one of the allowed values"}];
return false;
}
var valid0 = _errs4 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.request_id !== undefined){
let data2 = data.request_id;
const _errs6 = errors;
if(errors === _errs6){
if(typeof data2 === "string"){
if(func2(data2) > 128){
validate58.errors = [{instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func2(data2) < 1){
validate58.errors = [{instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate58.errors = [{instancePath:instancePath+"/request_id",schemaPath:"#/properties/request_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs6 === errors;
}
else {
var valid0 = true;
}
if(valid0){
if(data.session_id !== undefined){
let data3 = data.session_id;
const _errs8 = errors;
if(errors === _errs8){
if(typeof data3 === "string"){
if(func2(data3) > 128){
validate58.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/maxLength",keyword:"maxLength",params:{limit: 128},message:"must NOT have more than 128 characters"}];
return false;
}
else {
if(func2(data3) < 1){
validate58.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/minLength",keyword:"minLength",params:{limit: 1},message:"must NOT have fewer than 1 characters"}];
return false;
}
}
}
else {
validate58.errors = [{instancePath:instancePath+"/session_id",schemaPath:"#/properties/session_id/type",keyword:"type",params:{type: "string"},message:"must be string"}];
return false;
}
}
var valid0 = _errs8 === errors;
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
validate58.errors = [{instancePath,schemaPath:"#/type",keyword:"type",params:{type: "object"},message:"must be object"}];
return false;
}
}
validate58.errors = vErrors;
return errors === 0;
}
validate58.evaluated = {"props":true,"dynamicProps":false,"dynamicItems":false};


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
const _errs0 = errors;
let valid0 = false;
let passing0 = null;
const _errs1 = errors;
if(!(validate56(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate56.errors : vErrors.concat(validate56.errors);
errors = vErrors.length;
}
var _valid0 = _errs1 === errors;
if(_valid0){
valid0 = true;
passing0 = 0;
var props0 = true;
}
const _errs2 = errors;
if(!(validate58(data, {instancePath,parentData,parentDataProperty,rootData,dynamicAnchors}))){
vErrors = vErrors === null ? validate58.errors : vErrors.concat(validate58.errors);
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
validate55.errors = vErrors;
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
validate55.errors = vErrors;
evaluated0.props = props0;
return errors === 0;
}
validate55.evaluated = {"dynamicProps":true,"dynamicItems":false};
