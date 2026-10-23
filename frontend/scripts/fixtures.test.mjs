import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import Ajv from 'ajv';
import formats from 'ajv-formats';
const read=name=>JSON.parse(readFileSync(new URL(`../../fixtures/${name}.json`,import.meta.url)));
const spec=read('openapi');const ajv=new Ajv({strict:false});formats(ajv);ajv.addSchema({$id:'contract',components:spec.components});const validate=ajv.compile({$ref:'contract#/components/schemas/TaskView'});
for(const name of ['successful-task','failed-task','policy-denied-proposal','model-invalid-response','empty-context-with-warnings'])test(`${name} matches v1 TaskView`,()=>assert(validate(read(name)),ajv.errorsText(validate.errors)));
test('fixture set covers approval denial and recoverable failure',()=>{assert.equal(read('policy-denied-proposal').analysis.proposals[0].policy_ok,false);assert.equal(read('failed-task').error.retryable,true);assert.equal(read('successful-task').action_results[0].status,'ok');});
